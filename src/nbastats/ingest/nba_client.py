"""Cliente de stats.nba.com con control de ritmo y reintentos.

Debe ejecutarse **desde una máquina doméstica**. stats.nba.com está detrás de
protección Akamai que descarta conexiones desde IPs de datacenter (AWS, GCP,
Azure) sin devolver error: la petición simplemente se queda colgada hasta el
timeout. El backend sí puede desplegarse a la nube; esta ingesta no.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from nbastats.config import get_settings
from nbastats.db.models import SeasonType

logger = logging.getLogger(__name__)


# Nombres que espera la API para cada tipo de temporada.
SEASON_TYPE_PARAM: dict[SeasonType, str] = {
    SeasonType.REGULAR: "Regular Season",
    SeasonType.PLAYOFFS: "Playoffs",
    SeasonType.PLAYIN: "PlayIn",
    SeasonType.PRESEASON: "Pre Season",
}


# Zona horaria IANA del estadio de cada equipo.
#
# Se mapea por equipo y no por estado porque hay dos excepciones que rompen
# cualquier agrupación geográfica ingenua:
#   - Phoenix NO aplica horario de verano (America/Phoenix), a diferencia del
#     resto de Arizona Mountain Time. En verano coincide con la costa oeste y en
#     invierno con Denver.
#   - Indiana tiene su propia zona histórica (America/Indiana/Indianapolis).
#   - Toronto es Canadá: misma hora que Nueva York, pero zona distinta.
#
# Estas zonas alimentan `game_date_local`, del que dependen todos los splits por
# día de la semana.
ARENA_TIMEZONES: dict[int, str] = {
    1610612737: "America/New_York",              # ATL Atlanta
    1610612738: "America/New_York",              # BOS Boston
    1610612751: "America/New_York",              # BKN Brooklyn
    1610612766: "America/New_York",              # CHA Charlotte
    1610612741: "America/Chicago",               # CHI Chicago
    1610612739: "America/New_York",              # CLE Cleveland
    1610612742: "America/Chicago",               # DAL Dallas
    1610612743: "America/Denver",                # DEN Denver
    1610612765: "America/New_York",              # DET Detroit
    1610612744: "America/Los_Angeles",           # GSW San Francisco
    1610612745: "America/Chicago",               # HOU Houston
    1610612754: "America/Indiana/Indianapolis",  # IND Indiana
    1610612746: "America/Los_Angeles",           # LAC Los Angeles
    1610612747: "America/Los_Angeles",           # LAL Los Angeles
    1610612763: "America/Chicago",               # MEM Memphis
    1610612748: "America/New_York",              # MIA Miami
    1610612749: "America/Chicago",               # MIL Milwaukee
    1610612750: "America/Chicago",               # MIN Minnesota
    1610612740: "America/Chicago",               # NOP New Orleans
    1610612752: "America/New_York",              # NYK New York
    1610612760: "America/Chicago",               # OKC Oklahoma City
    1610612753: "America/New_York",              # ORL Orlando
    1610612755: "America/New_York",              # PHI Philadelphia
    1610612756: "America/Phoenix",               # PHX Phoenix — sin horario de verano
    1610612757: "America/Los_Angeles",           # POR Portland
    1610612758: "America/Los_Angeles",           # SAC Sacramento
    1610612759: "America/Chicago",               # SAS San Antonio
    1610612761: "America/Toronto",               # TOR Toronto
    1610612762: "America/Denver",                # UTA Utah
    1610612764: "America/New_York",              # WAS Washington
}


class NBAApiError(RuntimeError):
    """Fallo al hablar con stats.nba.com tras agotar los reintentos."""


class NBAClient:
    """Envoltorio con control de ritmo sobre los endpoints de `nba_api`.

    El control de ritmo es global al proceso (un cerrojo compartido), no por
    instancia: stats.nba.com limita por IP, así que crear varios clientes no
    permitiría ir más rápido — solo conseguiría que nos bloqueen.
    """

    _lock = threading.Lock()
    _last_call: float = 0.0

    def __init__(
        self,
        *,
        delay_seconds: float | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        settings = get_settings()
        self.delay = delay_seconds if delay_seconds is not None else settings.nba_api_delay_seconds
        self.timeout = timeout if timeout is not None else settings.nba_api_timeout_seconds
        self.max_retries = (
            max_retries if max_retries is not None else settings.nba_api_max_retries
        )

    def _throttle(self) -> None:
        with NBAClient._lock:
            elapsed = time.monotonic() - NBAClient._last_call
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            NBAClient._last_call = time.monotonic()

    def _call(self, endpoint_cls: Any, **params: Any) -> list[dict]:
        """Ejecuta un endpoint y devuelve sus filas como diccionarios."""

        @retry(
            stop=stop_after_attempt(self.max_retries),
            # Espera creciente: 2s, 4s, 8s, 16s. Los bloqueos de stats.nba.com
            # son temporales; insistir rápido solo los prolonga.
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        def _attempt() -> list[dict]:
            self._throttle()
            result = endpoint_cls(timeout=self.timeout, **params)
            return _extract_rows(result)

        try:
            rows = _attempt()
        except Exception as exc:  # noqa: BLE001 — se reenvía envuelto
            raise NBAApiError(
                f"{endpoint_cls.__name__} falló tras {self.max_retries} intentos "
                f"con {params}: {exc}"
            ) from exc

        logger.debug("%s(%s) -> %d filas", endpoint_cls.__name__, params, len(rows))
        return rows

    # --- Endpoints ---------------------------------------------------

    def player_game_logs(
        self,
        season: str,
        season_type: SeasonType,
        *,
        advanced: bool = False,
    ) -> list[dict]:
        """Box scores de jugador de una temporada entera, en una sola llamada.

        Devuelve ~26.000 filas por temporada regular en ~1 segundo. Con
        `advanced=True` trae TS%, eFG%, USG%, ratings, PACE, POSS y PIE.
        """
        from nba_api.stats.endpoints import playergamelogs

        params: dict[str, Any] = {
            "season_nullable": season,
            "season_type_nullable": SEASON_TYPE_PARAM[season_type],
        }
        if advanced:
            params["measure_type_player_game_logs_nullable"] = "Advanced"
        return self._call(playergamelogs.PlayerGameLogs, **params)

    def team_game_logs(
        self,
        season: str,
        season_type: SeasonType,
        *,
        advanced: bool = False,
    ) -> list[dict]:
        """Box scores de equipo de una temporada entera (2 filas por partido)."""
        from nba_api.stats.endpoints import teamgamelogs

        params: dict[str, Any] = {
            "season_nullable": season,
            "season_type_nullable": SEASON_TYPE_PARAM[season_type],
        }
        if advanced:
            params["measure_type_player_game_logs_nullable"] = "Advanced"
        return self._call(teamgamelogs.TeamGameLogs, **params)

    def scoreboard(self, game_date: str) -> list[dict]:
        """Partidos de una fecha, con hora de salto inicial en UTC.

        Se usa ScoreboardV3 y no V2: la V2 tiene fallos documentados en el
        *line score* de la temporada 2025-26, que es una de las nuestras.
        """
        from nba_api.stats.endpoints import scoreboardv3

        self._throttle()
        data = scoreboardv3.ScoreboardV3(
            game_date=game_date, timeout=self.timeout
        ).get_dict()
        return data.get("scoreboard", {}).get("games", [])

    @staticmethod
    def static_teams() -> list[dict]:
        """Los 30 equipos, desde el paquete estático (sin petición de red)."""
        from nba_api.stats.static import teams

        return teams.get_teams()


def _extract_rows(result: Any) -> list[dict]:
    """Convierte la respuesta de un endpoint en una lista de diccionarios.

    Se trabaja sobre el JSON crudo (`headers` + `rowSet`) en vez de pasar por
    `get_data_frames()` para no arrastrar pandas en la ruta de ingesta: son
    ~140.000 filas y el DataFrame intermedio no aporta nada.
    """
    payload = result.get_dict()

    result_sets = payload.get("resultSets") or payload.get("resultSet") or []
    if isinstance(result_sets, dict):
        result_sets = [result_sets]
    if not result_sets:
        return []

    first = result_sets[0]
    headers = first.get("headers", [])
    return [dict(zip(headers, row, strict=True)) for row in first.get("rowSet", [])]
