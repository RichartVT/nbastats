"""Carga en bloque de temporadas completas.

Estrategia: `PlayerGameLogs` y `TeamGameLogs` devuelven una temporada entera en
una sola petición (~26.000 filas en ~1 s). Con 4 peticiones por temporada y tipo
—jugador base, jugador avanzado, equipo base, equipo avanzado— se reconstruyen
las 7 tablas del esquema.

Todo se escribe con `UPSERT`, así que reejecutar la carga es seguro e
idempotente. Importa: la NBA revisa box scores días después del partido, y la
única forma de recoger esas correcciones es volver a cargar encima.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from nbastats.db.models import (
    Game,
    IngestLog,
    Player,
    PlayerGameAdvanced,
    PlayerGameStats,
    Season,
    SeasonType,
    Team,
    TeamGameStats,
)
from nbastats.db.session import session_scope
from nbastats.ingest.nba_client import ARENA_TIMEZONES, NBAClient
from nbastats.ingest.transforms import (
    parse_game_id,
    parse_minutes,
    season_start_year,
)

logger = logging.getLogger(__name__)

# Postgres admite ~65.535 parámetros por sentencia. Con ~35 columnas por fila,
# 1.000 filas por lote deja margen holgado.
CHUNK_SIZE = 1000

# Duración reglamentaria de un partido, en minutos. Cada prórroga añade 5.
REGULATION_MINUTES = 48
OVERTIME_MINUTES = 5


@dataclass
class IngestResult:
    season: str
    season_type: SeasonType
    games: int = 0
    team_rows: int = 0
    player_rows: int = 0
    advanced_rows: int = 0
    players_seen: int = 0
    skipped: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    def __str__(self) -> str:
        return (
            f"{self.season} {self.season_type.value:>8}: "
            f"{self.games:>5,} partidos | {self.player_rows:>7,} filas jugador | "
            f"{self.advanced_rows:>7,} avanzadas | {self.duration_s:.1f}s"
        )


# =========================================================================
# Utilidades
# =========================================================================


def _chunked(rows: Sequence[dict], size: int = CHUNK_SIZE) -> Iterable[Sequence[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def upsert(
    session: Session, model: type, rows: Sequence[dict], *, keys: Sequence[str]
) -> int:
    """Inserta o actualiza por lotes.

    Se actualizan todas las columnas que no formen parte de la clave. Es lo
    correcto aquí: la fuente es autoritativa y una recarga debe traer las
    correcciones oficiales de la NBA, no conservar el valor viejo.
    """
    if not rows:
        return 0

    updatable = [c.name for c in model.__table__.columns if c.name not in keys]

    for chunk in _chunked(rows):
        stmt = pg_insert(model).values(list(chunk))
        stmt = stmt.on_conflict_do_update(
            index_elements=list(keys),
            set_={name: stmt.excluded[name] for name in updatable},
        )
        session.execute(stmt)

    return len(rows)


def _game_date(raw: str | None) -> dt.date | None:
    """'2025-04-13T00:00:00' -> date(2025, 4, 13).

    La API entrega la fecha SIN hora, y está verificado que corresponde a la
    fecha local del estadio (45 partidos en 6 fechas, incluidos los dos cambios
    de horario de verano, cero discrepancias). Por eso se puede usar
    directamente como `game_date_local`.
    """
    if not raw:
        return None
    return dt.date.fromisoformat(str(raw)[:10])


def _is_home(matchup: str | None) -> bool | None:
    """'MEM vs. DAL' -> local. 'LAC @ GSW' -> visitante."""
    if not matchup:
        return None
    if " vs. " in matchup:
        return True
    if " @ " in matchup:
        return False
    return None


def _overtime_periods(team_minutes: float | None) -> int:
    """Prórrogas a partir de los minutos de partido del equipo.

    48 minutos = reglamentario; cada prórroga suma 5. Se redondea porque en
    partidos con expulsiones o finales atípicos el valor puede venir con
    decimales.
    """
    if team_minutes is None:
        return 0
    extra = float(team_minutes) - REGULATION_MINUTES
    return max(0, round(extra / OVERTIME_MINUTES))


def _num(value: Any) -> Any:
    """Normaliza NaN a None; el resto pasa tal cual."""
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def _fraction(value: Any) -> Any:
    """Convierte un porcentaje en escala 0-100 a fracción 0-1.

    La API mezcla escalas dentro de una misma respuesta, sin avisar:

        TS_PCT, EFG_PCT, USG_PCT, AST_PCT, REB_PCT...  ->  0-1   (0.597)
        E_TOV_PCT, TM_TOV_PCT                          ->  0-100 (12.5)

    Guardarlo tal cual haría que el TOV% de un jugador saliera 100 veces mayor
    que su USG% en cualquier comparación o gráfico, sin que nada fallara. Se
    detectó porque un valor de 100.0 reventó el `Numeric(6,4)` de la columna —
    la restricción estrecha hizo su trabajo.
    """
    value = _num(value)
    return None if value is None else value / 100.0


# =========================================================================
# Dimensiones
# =========================================================================


def ensure_teams(session: Session) -> int:
    """Carga los 30 equipos desde el paquete estático (sin red)."""
    rows = [
        {
            "team_id": t["id"],
            "abbreviation": t["abbreviation"],
            "full_name": t["full_name"],
            "city": t.get("city"),
            "nickname": t.get("nickname"),
            "conference": None,
            "division": None,
            "arena_timezone": ARENA_TIMEZONES.get(t["id"]),
        }
        for t in NBAClient.static_teams()
    ]
    return upsert(session, Team, rows, keys=["team_id"])


def ensure_season(session: Session, season_id: str) -> None:
    year = season_start_year(season_id)
    upsert(
        session,
        Season,
        [{"season_id": season_id, "year_start": year, "year_end": year + 1}],
        keys=["season_id"],
    )


def ensure_players(session: Session, player_rows: Sequence[dict]) -> int:
    """Crea las filas mínimas de jugador vistas en los logs.

    Solo id y nombre. La biografía (fecha de nacimiento, altura, posición) llega
    después desde Kaggle: `PlayerGameLogs` no la trae y pedirla a `nba_api`
    costaría una llamada por jugador.

    El UPSERT aquí actualiza únicamente el nombre — si sobreescribiera todas las
    columnas, cada recarga borraría las biografías ya cargadas.
    """
    vistos: dict[int, dict] = {}
    for row in player_rows:
        pid = row.get("PLAYER_ID")
        if pid is None:
            continue
        nombre = (row.get("PLAYER_NAME") or "").strip()
        partes = nombre.split(" ", 1)
        vistos[pid] = {
            "player_id": pid,
            "full_name": nombre,
            "first_name": partes[0] if partes else None,
            "last_name": partes[1] if len(partes) > 1 else None,
        }

    if not vistos:
        return 0

    rows = list(vistos.values())
    for chunk in _chunked(rows):
        stmt = pg_insert(Player).values(list(chunk))
        stmt = stmt.on_conflict_do_update(
            index_elements=["player_id"],
            set_={
                "full_name": stmt.excluded.full_name,
                "first_name": stmt.excluded.first_name,
                "last_name": stmt.excluded.last_name,
            },
        )
        session.execute(stmt)
    return len(rows)


# =========================================================================
# Hechos
# =========================================================================


def _resolve_neutral_sites(
    pendientes: dict[str, list[dict]], client: NBAClient
) -> dict[str, int]:
    """Averigua el local nominal de los partidos en sede neutral.

    En un partido neutral (París, Ciudad de México, Las Vegas para la NBA Cup)
    `MATCHUP` marca a AMBOS equipos como visitantes con `@`, así que no hay
    forma de deducir el local del propio log. `ScoreboardV3` sí lo declara.

    Se agrupa por fecha para gastar una petición por día y no por partido: los
    neutrales suelen caer de dos en dos el mismo día.
    """
    if not pendientes:
        return {}

    por_fecha: dict[str, list[str]] = {}
    for gid, filas in pendientes.items():
        fecha = str(filas[0].get("GAME_DATE") or "")[:10]
        if fecha:
            por_fecha.setdefault(fecha, []).append(gid)

    locales: dict[str, int] = {}
    for fecha, ids in por_fecha.items():
        try:
            juegos = {g["gameId"]: g for g in client.scoreboard(fecha)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo resolver la sede neutral de %s: %s", fecha, exc)
            continue
        for gid in ids:
            juego = juegos.get(gid)
            if juego:
                locales[gid] = juego["homeTeam"]["teamId"]

    return locales


def _build_games(
    team_base: Sequence[dict], skipped: list[str], client: NBAClient
) -> tuple[list[dict], dict[str, dict[int, int]]]:
    """Reconstruye `games` a partir de las dos filas de equipo de cada partido.

    Devuelve además, por partido, el mapa equipo -> rival, que hace falta para
    rellenar `opponent_team_id` en team_game_stats.
    """
    por_partido: dict[str, list[dict]] = {}
    for row in team_base:
        gid = row.get("GAME_ID")
        if gid:
            por_partido.setdefault(str(gid), []).append(row)

    # Primera pasada: detectar los neutrales para resolverlos en bloque.
    neutrales = {
        gid: filas
        for gid, filas in por_partido.items()
        if len(filas) == 2
        and all(_is_home(f.get("MATCHUP")) is False for f in filas)
    }
    locales_neutrales = _resolve_neutral_sites(neutrales, client)
    if neutrales:
        logger.info(
            "%d partidos en sede neutral, %d resueltos",
            len(neutrales),
            len(locales_neutrales),
        )

    juegos: list[dict] = []
    rivales: dict[str, dict[int, int]] = {}

    for gid, filas in por_partido.items():
        if len(filas) != 2:
            # Un partido siempre tiene exactamente dos equipos. Si no, el dato
            # está incompleto y meterlo corrompería los agregados.
            skipped.append(f"{gid}: {len(filas)} filas de equipo (se esperaban 2)")
            continue

        try:
            season_id, season_type = parse_game_id(gid)
        except ValueError as exc:
            skipped.append(f"{gid}: {exc}")
            continue

        es_neutral = gid in neutrales
        if es_neutral:
            home_id = locales_neutrales.get(gid)
            if home_id is None:
                skipped.append(f"{gid}: sede neutral sin local resoluble")
                continue
            local = next(f for f in filas if f["TEAM_ID"] == home_id)
            visitante = next(f for f in filas if f["TEAM_ID"] != home_id)
        else:
            local = next((f for f in filas if _is_home(f.get("MATCHUP"))), None)
            visitante = next(
                (f for f in filas if _is_home(f.get("MATCHUP")) is False), None
            )
            if local is None or visitante is None:
                skipped.append(f"{gid}: no se pudo determinar local/visitante")
                continue

        fecha = _game_date(local.get("GAME_DATE"))
        if fecha is None:
            skipped.append(f"{gid}: sin fecha")
            continue

        juegos.append(
            {
                "game_id": gid,
                "season_id": season_id,
                "season_type": season_type,
                "game_date_local": fecha,
                "tipoff_utc": None,
                "home_team_id": local["TEAM_ID"],
                "away_team_id": visitante["TEAM_ID"],
                "home_pts": _num(local.get("PTS")),
                "away_pts": _num(visitante.get("PTS")),
                "ot_periods": _overtime_periods(local.get("MIN")),
                "attendance": None,
                "arena_name": None,
                "is_neutral_site": es_neutral,
            }
        )
        rivales[gid] = {
            local["TEAM_ID"]: visitante["TEAM_ID"],
            visitante["TEAM_ID"]: local["TEAM_ID"],
        }

    return juegos, rivales


def _build_team_stats(
    team_base: Sequence[dict],
    team_adv: Sequence[dict],
    rivales: dict[str, dict[int, int]],
    home_by_game: dict[str, int],
    team_misc: Sequence[dict] = (),
) -> list[dict]:
    avanzadas = {
        (str(r["GAME_ID"]), r["TEAM_ID"]): r for r in team_adv if r.get("GAME_ID")
    }
    # `Misc` va como tercer MeasureType de la misma llamada masiva: una petición
    # por temporada y tipo, no una por partido.
    miscelanea = {
        (str(r["GAME_ID"]), r["TEAM_ID"]): r for r in team_misc if r.get("GAME_ID")
    }

    filas = []
    for row in team_base:
        gid = str(row.get("GAME_ID") or "")
        tid = row.get("TEAM_ID")
        if gid not in rivales or tid is None:
            continue

        adv = avanzadas.get((gid, tid), {})
        misc = miscelanea.get((gid, tid), {})
        filas.append(
            {
                "game_id": gid,
                "team_id": tid,
                "opponent_team_id": rivales[gid][tid],
                # Se toma del local ya resuelto en `games`, no de MATCHUP: en
                # sede neutral MATCHUP marca a los dos equipos como visitantes.
                "is_home": home_by_game.get(gid) == tid,
                "won": (row.get("WL") == "W") if row.get("WL") else None,
                # Duración del partido, no la suma de los 5 puestos.
                "seconds_played": int((row.get("MIN") or 0) * 60),
                "pts": _num(row.get("PTS")),
                "fgm": _num(row.get("FGM")),
                "fga": _num(row.get("FGA")),
                "fg3m": _num(row.get("FG3M")),
                "fg3a": _num(row.get("FG3A")),
                "ftm": _num(row.get("FTM")),
                "fta": _num(row.get("FTA")),
                "oreb": _num(row.get("OREB")),
                "dreb": _num(row.get("DREB")),
                "reb": _num(row.get("REB")),
                "ast": _num(row.get("AST")),
                "stl": _num(row.get("STL")),
                "blk": _num(row.get("BLK")),
                "tov": _num(row.get("TOV")),
                "pf": _num(row.get("PF")),
                "plus_minus": _num(row.get("PLUS_MINUS")),
                "possessions": _num(adv.get("POSS")),
                "pace": _num(adv.get("PACE")),
                "off_rating": _num(adv.get("OFF_RATING")),
                "def_rating": _num(adv.get("DEF_RATING")),
                "net_rating": _num(adv.get("NET_RATING")),
                "efg_pct": _num(adv.get("EFG_PCT")),
                "ts_pct": _num(adv.get("TS_PCT")),
                # De dónde salieron los puntos. Vacío si no se pidió `Misc`.
                "pts_paint": _num(misc.get("PTS_PAINT")),
                "pts_fastbreak": _num(misc.get("PTS_FB")),
                "pts_off_turnovers": _num(misc.get("PTS_OFF_TOV")),
                "pts_2nd_chance": _num(misc.get("PTS_2ND_CHANCE")),
                "opp_pts_paint": _num(misc.get("OPP_PTS_PAINT")),
                "opp_pts_fastbreak": _num(misc.get("OPP_PTS_FB")),
                "opp_pts_off_turnovers": _num(misc.get("OPP_PTS_OFF_TOV")),
                "opp_pts_2nd_chance": _num(misc.get("OPP_PTS_2ND_CHANCE")),
                # Estas cuatro se calculan DESPUÉS, en db/sql/derive.sql:
                # dependen de los partidos anteriores del equipo, que pueden no
                # estar cargados todavía. Se pasan explícitas a None porque el
                # upsert pone a NULL toda columna ausente, y verlas aquí evita
                # que alguien las busque en vano en la respuesta de la API.
                "rest_days": None,
                "is_back_to_back": None,
                "wins_before": None,
                "losses_before": None,
            }
        )
    return filas


def _build_player_stats(
    player_base: Sequence[dict], validos: set[str]
) -> list[dict]:
    filas = []
    for row in player_base:
        gid = str(row.get("GAME_ID") or "")
        if gid not in validos:
            continue

        filas.append(
            {
                "game_id": gid,
                "player_id": row["PLAYER_ID"],
                "team_id": row["TEAM_ID"],
                # MIN_SEC llega como "48:24"; MIN como 48.4. Se prefiere el
                # primero por precisión, con el segundo de respaldo.
                "seconds_played": parse_minutes(
                    row.get("MIN_SEC") if row.get("MIN_SEC") else row.get("MIN")
                ),
                # PlayerGameLogs no distingue titular de suplente ni informa de
                # los DNP: solo aparecen los que jugaron. Ver CAPABILITIES.md.
                "started": None,
                "dnp_reason": None,
                "pts": _num(row.get("PTS")),
                "fgm": _num(row.get("FGM")),
                "fga": _num(row.get("FGA")),
                "fg3m": _num(row.get("FG3M")),
                "fg3a": _num(row.get("FG3A")),
                "ftm": _num(row.get("FTM")),
                "fta": _num(row.get("FTA")),
                "oreb": _num(row.get("OREB")),
                "dreb": _num(row.get("DREB")),
                "reb": _num(row.get("REB")),
                "ast": _num(row.get("AST")),
                "stl": _num(row.get("STL")),
                "blk": _num(row.get("BLK")),
                "tov": _num(row.get("TOV")),
                "pf": _num(row.get("PF")),
                "plus_minus": _num(row.get("PLUS_MINUS")),
            }
        )
    return filas


def _build_player_advanced(
    player_adv: Sequence[dict], validos: set[str]
) -> list[dict]:
    filas = []
    for row in player_adv:
        gid = str(row.get("GAME_ID") or "")
        if gid not in validos:
            continue

        filas.append(
            {
                "game_id": gid,
                "player_id": row["PLAYER_ID"],
                "ts_pct": _num(row.get("TS_PCT")),
                "efg_pct": _num(row.get("EFG_PCT")),
                "usg_pct": _num(row.get("USG_PCT")),
                "ast_pct": _num(row.get("AST_PCT")),
                "reb_pct": _num(row.get("REB_PCT")),
                "oreb_pct": _num(row.get("OREB_PCT")),
                "dreb_pct": _num(row.get("DREB_PCT")),
                # Escala 0-100 en origen, a diferencia del resto. Ver _fraction().
                "tov_pct": _fraction(row.get("E_TOV_PCT")),
                "off_rating": _num(row.get("OFF_RATING")),
                "def_rating": _num(row.get("DEF_RATING")),
                "net_rating": _num(row.get("NET_RATING")),
                "pace": _num(row.get("PACE")),
                "pie": _num(row.get("PIE")),
            }
        )
    return filas


# =========================================================================
# Orquestación
# =========================================================================


def ingest_season(
    season: str,
    season_type: SeasonType,
    *,
    client: NBAClient | None = None,
) -> IngestResult:
    """Carga una temporada y tipo de temporada completos (4 peticiones)."""
    client = client or NBAClient()
    result = IngestResult(season=season, season_type=season_type)
    t0 = time.monotonic()

    team_base = client.team_game_logs(season, season_type)
    if not team_base:
        logger.warning("Sin datos para %s %s", season, season_type.value)
        result.duration_s = time.monotonic() - t0
        return result

    team_adv = client.team_game_logs(season, season_type, advanced=True)
    team_misc = client.team_game_logs(season, season_type, measure_type="Misc")
    player_base = client.player_game_logs(season, season_type)
    player_adv = client.player_game_logs(season, season_type, advanced=True)

    juegos, rivales = _build_games(team_base, result.skipped, client)
    validos = set(rivales)
    home_by_game = {g["game_id"]: g["home_team_id"] for g in juegos}

    with session_scope() as session:
        # Orden obligado por las claves ajenas.
        ensure_teams(session)
        ensure_season(session, season)
        result.players_seen = ensure_players(session, player_base)

        result.games = upsert(session, Game, juegos, keys=["game_id"])
        result.team_rows = upsert(
            session,
            TeamGameStats,
            _build_team_stats(team_base, team_adv, rivales, home_by_game, team_misc),
            keys=["game_id", "team_id"],
        )
        result.player_rows = upsert(
            session,
            PlayerGameStats,
            _build_player_stats(player_base, validos),
            keys=["game_id", "player_id"],
        )
        result.advanced_rows = upsert(
            session,
            PlayerGameAdvanced,
            _build_player_advanced(player_adv, validos),
            keys=["game_id", "player_id"],
        )

        session.add(
            IngestLog(
                source="nba_api",
                endpoint="PlayerGameLogs+TeamGameLogs",
                params={"season": season, "season_type": season_type.value},
                fetched_at=dt.datetime.now(dt.UTC),
                status="ok",
                rows_written=result.player_rows + result.team_rows,
            )
        )

    result.duration_s = time.monotonic() - t0
    if result.skipped:
        logger.warning(
            "%s %s: %d partidos descartados. Primeros: %s",
            season,
            season_type.value,
            len(result.skipped),
            result.skipped[:3],
        )
    logger.info("%s", result)
    return result


def ingest_seasons(
    seasons: Sequence[str],
    season_types: Sequence[SeasonType] = (
        SeasonType.REGULAR,
        SeasonType.PLAYIN,
        SeasonType.PLAYOFFS,
    ),
) -> list[IngestResult]:
    """Carga varias temporadas. La operación completa del proyecto."""
    client = NBAClient()
    resultados = []
    for season in seasons:
        for season_type in season_types:
            resultados.append(ingest_season(season, season_type, client=client))
    return resultados
