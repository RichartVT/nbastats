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
    retry_if_not_exception_type,
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


# Errores que delatan una respuesta con otra forma, no una red que falla.
_ERRORES_DE_FORMA = (AttributeError, KeyError, TypeError, IndexError)


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

    def _call_raw(self, endpoint_cls: Any, **params: Any) -> dict:
        """Ejecuta un endpoint con control de ritmo y reintentos, sin interpretar.

        Existe separado de `_call` porque los endpoints V3 no devuelven el
        formato `resultSets` de siempre, sino un JSON anidado con su propia
        forma. Sin esta separación, usarlos obligaba a llamar a `_throttle()`
        a pelo y quedarse **sin reintentos** — que es justo lo que no se puede
        permitir un bucle de 6.600 peticiones, donde un corte de red pasajero
        tiraría la pasada entera.
        """

        @retry(
            stop=stop_after_attempt(self.max_retries),
            # Espera creciente: 2s, 4s, 8s, 16s. Los bloqueos de stats.nba.com
            # son temporales; insistir rápido solo los prolonga.
            wait=wait_exponential(multiplier=2, min=2, max=30),
            # NO se reintenta ante errores de FORMA. Un `AttributeError` o un
            # `KeyError` significan que la respuesta no tiene la estructura
            # esperada, y eso no se arregla insistiendo: o es un fallo nuestro
            # de parseo o la fuente ha devuelto un hueco. Reintentarlo cinco
            # veces con espera creciente son 30 segundos tirados por partido —
            # sobre una pasada de 6.600, media hora de nada.
            retry=retry_if_not_exception_type(_ERRORES_DE_FORMA),
            reraise=True,
        )
        def _attempt() -> dict:
            self._throttle()
            return endpoint_cls(timeout=self.timeout, **params).get_dict()

        try:
            return _attempt()
        except Exception as exc:  # noqa: BLE001 — se reenvía envuelto
            raise NBAApiError(
                f"{endpoint_cls.__name__} falló tras {self.max_retries} intentos "
                f"con {params}: {exc}"
            ) from exc

    def _call(self, endpoint_cls: Any, **params: Any) -> list[dict]:
        """Ejecuta un endpoint y devuelve sus filas como diccionarios."""
        rows = _extract_rows(self._call_raw(endpoint_cls, **params))
        logger.debug("%s(%s) -> %d filas", endpoint_cls.__name__, params, len(rows))
        return rows

    # --- Endpoints ---------------------------------------------------

    def player_game_logs(
        self,
        season: str,
        season_type: SeasonType,
        *,
        advanced: bool = False,
        period: int | None = None,
    ) -> list[dict]:
        """Box scores de jugador de una temporada entera, en una sola llamada.

        Devuelve ~26.000 filas por temporada regular en ~1 segundo. Con
        `advanced=True` trae TS%, eFG%, USG%, ratings, PACE, POSS y PIE.

        Con `period=N` devuelve lo mismo pero **restringido a ese periodo**: una
        fila por jugador-partido con lo que hizo en ese cuarto. Es lo que hace
        que el desglose por cuarto de las cinco temporadas cueste ~75 peticiones
        en vez de las ~26.400 que costaría pedir `BoxScoreTraditionalV3` partido
        a partido y periodo a periodo.

        Comprobado antes de fiarse, porque la API ignora parámetros en silencio
        con cierta frecuencia: sumando los periodos 1-4 de 2024-25 se reproduce
        el total del partido en el 98,6% de los 26.304 jugador-partido, y el
        1,4% restante son exactamente los partidos con prórroga, donde faltaban
        los periodos 5 y 6.
        """
        from nba_api.stats.endpoints import playergamelogs

        params: dict[str, Any] = {
            "season_nullable": season,
            "season_type_nullable": SEASON_TYPE_PARAM[season_type],
        }
        if advanced:
            params["measure_type_player_game_logs_nullable"] = "Advanced"
        if period is not None:
            params["period_nullable"] = period
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

    def team_details(self, team_id: int) -> dict[str, list[dict]]:
        """Ficha de la franquicia: estadio, capacidad, propietario, GM, entrenador.

        Devuelve TODOS los bloques del endpoint indexados por nombre
        (`TeamBackground`, `TeamHistory`, `TeamAwardsChampionships`...), no solo
        el primero, porque aquí el interesante no siempre es el bloque inicial.
        """
        from nba_api.stats.endpoints import teamdetails

        self._throttle()
        payload = teamdetails.TeamDetails(
            team_id=team_id, timeout=self.timeout
        ).get_dict()
        return {
            r["name"]: [dict(zip(r["headers"], fila, strict=True)) for fila in r["rowSet"]]
            for r in payload.get("resultSets", [])
        }

    def team_roster(self, team_id: int, season: str) -> dict[str, list[dict]]:
        """Plantilla y cuerpo técnico de un equipo en una temporada."""
        from nba_api.stats.endpoints import commonteamroster

        self._throttle()
        payload = commonteamroster.CommonTeamRoster(
            team_id=team_id, season=season, timeout=self.timeout
        ).get_dict()
        return {
            r["name"]: [dict(zip(r["headers"], fila, strict=True)) for fila in r["rowSet"]]
            for r in payload.get("resultSets", [])
        }

    def game_summary(self, game_id: str) -> dict:
        """Resumen de un partido: marcador por periodo, pabellón, árbitros, inactivos.

        Una sola petición trae lo que hoy faltaba en cuatro sitios distintos:
        el desglose por cuarto, la asistencia y el pabellón (columnas que
        existen en `games` y siempre valen NULL), los árbitros, y los periodos
        de prórroga REALES — que hasta ahora se infieren dividiendo los minutos
        del equipo entre 5.

        Se usa la V3 y no la V2 por el mismo motivo que en `scoreboard()`: la
        familia V2 tiene fallos documentados en el *line score* de 2025-26, que
        es una de nuestras cinco temporadas. Aquí el line score es justo el dato
        que se viene a buscar.

        Devuelve el bloque `boxScoreSummary` tal cual: es un JSON anidado, no el
        formato `resultSets`, así que no pasa por `_extract_rows`.
        """
        from nba_api.stats.endpoints import boxscoresummaryv3

        # Un puñado de partidos (3 de 6.602 en las cinco temporadas) devuelven
        # el resumen con TODOS los campos a null, y el parser de `nba_api`
        # revienta al leerlos. No es un fallo de red ni nuestro: es un hueco de
        # la fuente. Se devuelve vacío para que el llamador lo registre como
        # "sin resumen" en vez de propagar un error que no se puede arreglar.
        try:
            payload = self._call_raw(boxscoresummaryv3.BoxScoreSummaryV3, game_id=game_id)
        except NBAApiError as exc:
            if isinstance(exc.__cause__, _ERRORES_DE_FORMA):
                logger.warning("La NBA no tiene resumen del partido %s", game_id)
                return {}
            raise
        return payload.get("boxScoreSummary") or {}

    def play_by_play(self, game_id: str) -> list[dict]:
        """Todos los eventos de un partido, ~525.

        Devuelve el crudo `game.actions` en vez de pasar por el parser de
        `nba_api`, que construye cada fila con una lista FIJA de 24 campos y
        descarta en silencio lo que no esté en ella. Aquí interesa el payload
        entero: las coordenadas de tiro vienen dentro y son las que hacen
        innecesario `ShotChartDetail`.
        """
        from nba_api.stats.endpoints import playbyplayv3

        payload = self._call_raw(playbyplayv3.PlayByPlayV3, game_id=game_id)
        return (payload.get("game") or {}).get("actions") or []

    def standings(self, season: str, season_type: str = "Regular Season") -> list[dict]:
        """Clasificación oficial, con los desempates de la NBA ya aplicados.

        `PlayoffRank` llega calculado. Recalcularlo por nuestra cuenta sería
        reimplementar un reglamento lleno de casos particulares para obtener,
        en el mejor de los casos, el mismo número.
        """
        from nba_api.stats.endpoints import leaguestandingsv3

        return self._call(
            leaguestandingsv3.LeagueStandingsV3,
            season=season,
            season_type=season_type,
        )

    @staticmethod
    def static_teams() -> list[dict]:
        """Los 30 equipos, desde el paquete estático (sin petición de red)."""
        from nba_api.stats.static import teams

        return teams.get_teams()


def _extract_rows(payload: dict) -> list[dict]:
    """Convierte la respuesta de un endpoint en una lista de diccionarios.

    Se trabaja sobre el JSON crudo (`headers` + `rowSet`) en vez de pasar por
    `get_data_frames()` para no arrastrar pandas en la ruta de ingesta: son
    ~140.000 filas y el DataFrame intermedio no aporta nada.
    """
    result_sets = payload.get("resultSets") or payload.get("resultSet") or []
    if isinstance(result_sets, dict):
        result_sets = [result_sets]
    if not result_sets:
        return []

    first = result_sets[0]
    headers = first.get("headers", [])
    return [dict(zip(headers, row, strict=True)) for row in first.get("rowSet", [])]
