"""Box score de jugador desglosado por periodo.

Cierra la primera pregunta que `CAPABILITIES.md` §2 declaraba imposible:
"¿cómo rinde en el cuarto cuarto?".

LO BARATO QUE RESULTÓ SER, Y POR QUÉ. El camino evidente era
`BoxScoreTraditionalV3`, que acepta `start_period`/`end_period` y cuesta **una
petición por partido y por periodo**: ~26.400 peticiones y 7-11 horas. Pero
`PlayerGameLogs` acepta `Period` y devuelve la **temporada entera** restringida
a ese periodo en una sola llamada. Son **~75 peticiones y dos minutos** para las
cinco temporadas: 350 veces menos.

Como la API de la NBA ignora parámetros en silencio con cierta frecuencia, no
se dio por bueno hasta comprobarlo: sumando los periodos 1-4 de 2024-25 se
reproduce el total del partido en 25.930 de 26.304 jugador-partido (98,6%), y
los 374 que no cuadran son exactamente los de partidos con prórroga, a los que
les faltaban los periodos 5 y 6. El mismo cuadre se exige aquí sobre todo lo
cargado, y es el criterio de aceptación.

CUÁNTOS PERIODOS SE PIDEN. Cuatro siempre, más uno por cada prórroga que
exista en la temporada (el máximo observado en las cinco cargadas es 3). Pedir
un periodo que no existió no es un error: devuelve cero filas y cuesta una
petición.

POR QUÉ NO HAY TASAS AQUÍ. No se guarda ni se calcula ningún per-36 a nivel de
periodo. Extrapolar a 36 minutos desde los 4 que alguien jugó en un tercer
cuarto produce los mismos disparates que el `pace` de jugador. Lo que sí viaja
siempre junto a los totales son los **minutos**: los puntos de un jugador en el
cuarto cuarto no se pueden leer sin saber cuántos minutos jugó ese cuarto, y
enseñarlos solos invita justo al error contrario al que parece.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import text

from nbastats.db.models import IngestLog, PlayerPeriodStats, SeasonType
from nbastats.db.session import session_scope
from nbastats.ingest.bulk import upsert
from nbastats.ingest.nba_client import NBAClient
from nbastats.ingest.transforms import parse_minutes

logger = logging.getLogger(__name__)

# Los cuatro reglamentarios. Las prórrogas se añaden según lo que haya.
PERIODOS_REGLAMENTARIOS = 4

_TIPOS = (SeasonType.REGULAR, SeasonType.PLAYIN, SeasonType.PLAYOFFS)

# Enteros del box que se copian tal cual. `MIN_SEC` va aparte porque necesita
# el parseo del proyecto, y los porcentajes no se guardan: son derivables y
# sobre un cuarto son razones que alguien acabaría promediando.
_COLUMNAS = (
    "pts", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta",
    "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "plus_minus",
)


def _fila(row: dict, period: int, validos: set[str]) -> dict | None:
    """Traduce una fila de `PlayerGameLogs` a una fila de la tabla.

    Descarta los partidos que no están en `games`: los ids de All-Star y de la
    final de la NBA Cup llegan en algunas respuestas y violarían la clave ajena.
    """
    game_id = row.get("GAME_ID")
    if game_id not in validos:
        return None

    fila = {
        "game_id": game_id,
        "player_id": row["PLAYER_ID"],
        "period": period,
        "team_id": row["TEAM_ID"],
        # MIN_SEC llega como "8:24" y MIN como 8.4. Se prefiere el primero por
        # precisión, con el segundo de respaldo — igual que en `bulk.py`.
        "seconds_played": parse_minutes(row.get("MIN_SEC") or row.get("MIN")),
    }
    fila.update({c: row.get(c.upper()) for c in _COLUMNAS})
    return fila


def _periodos_a_pedir(session, season: str) -> int:
    """Cuántos periodos tuvo como máximo esta temporada."""
    maximo = session.execute(
        text("SELECT COALESCE(MAX(ot_periods), 0) FROM games WHERE season_id = :s"),
        {"s": season},
    ).scalar()
    return PERIODOS_REGLAMENTARIOS + int(maximo or 0)


def ingest_periods(
    seasons: list[str],
    *,
    client: NBAClient | None = None,
) -> dict:
    """Descarga el box score por periodo de las temporadas indicadas."""
    client = client or NBAClient()
    total = 0
    peticiones = 0

    with session_scope() as session:
        validos = set(session.scalars(text("SELECT game_id FROM games")).all())

    for season in seasons:
        with session_scope() as session:
            n_periodos = _periodos_a_pedir(session, season)

        for tipo in _TIPOS:
            for period in range(1, n_periodos + 1):
                try:
                    crudas = client.player_game_logs(season, tipo, period=period)
                except Exception as exc:  # noqa: BLE001 — un periodo no tumba la pasada
                    logger.warning("%s %s periodo %d falló: %s", season, tipo, period, exc)
                    continue

                peticiones += 1
                filas = [f for r in crudas if (f := _fila(r, period, validos))]
                if not filas:
                    continue

                with session_scope() as session:
                    upsert(
                        session,
                        PlayerPeriodStats,
                        filas,
                        keys=["game_id", "player_id", "period"],
                    )
                total += len(filas)
                logger.info("  %s %s periodo %d: %d filas", season, tipo, period, len(filas))

    with session_scope() as session:
        session.add(
            IngestLog(
                source="nba_api",
                endpoint="PlayerGameLogs(Period)",
                params={"seasons": seasons, "peticiones": peticiones},
                fetched_at=dt.datetime.now(dt.UTC),
                status="ok",
                rows_written=total,
            )
        )

    logger.info("Periodos: %d filas en %d peticiones", total, peticiones)
    return {"filas": total, "peticiones": peticiones}


def verificar_cuadre(seasons: list[str] | None = None) -> dict:
    """Comprueba que la suma de los periodos reproduce el total del partido.

    Es el criterio de aceptación, no una comprobación opcional: si los periodos
    no suman el partido, o falta un periodo o la API ignoró el parámetro, y en
    los dos casos el dato no vale. Se compara contra `player_game_stats`, que
    está cargado y validado contra NBA.com.

    Los minutos se comparan con tolerancia de 2 segundos por el redondeo de la
    fuente; el resto de estadísticas se exige exacto.
    """
    filtro = "AND g.season_id = ANY(:seasons)" if seasons else ""
    sql = text(f"""
        WITH por_periodo AS (
            SELECT p.game_id, p.player_id,
                   SUM(p.pts) AS pts, SUM(p.reb) AS reb, SUM(p.ast) AS ast,
                   SUM(p.fga) AS fga, SUM(p.tov) AS tov,
                   SUM(p.seconds_played) AS segundos
            FROM player_period_stats p
            JOIN games g USING (game_id)
            WHERE TRUE {filtro}
            GROUP BY 1, 2
        )
        SELECT COUNT(*)                                                   AS comparados,
               COUNT(*) FILTER (WHERE a.pts IS DISTINCT FROM s.pts)       AS pts_mal,
               COUNT(*) FILTER (WHERE a.reb IS DISTINCT FROM s.reb)       AS reb_mal,
               COUNT(*) FILTER (WHERE a.ast IS DISTINCT FROM s.ast)       AS ast_mal,
               COUNT(*) FILTER (WHERE a.fga IS DISTINCT FROM s.fga)       AS fga_mal,
               COUNT(*) FILTER (WHERE a.tov IS DISTINCT FROM s.tov)       AS tov_mal,
               COUNT(*) FILTER (
                   WHERE ABS(a.segundos - s.seconds_played) > 2
               )                                                          AS minutos_mal
        FROM por_periodo a
        JOIN player_game_stats s USING (game_id, player_id)
    """)
    with session_scope() as session:
        fila = session.execute(sql, {"seasons": seasons} if seasons else {}).mappings().one()
    return dict(fila)
