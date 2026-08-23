"""API HTTP.

    uv run uvicorn nbastats.api.main:app --reload
    -> http://localhost:8000/docs

Regla que gobierna toda la API: **ninguna respuesta devuelve un número solo.**
Los splits viajan con `n`, intervalo y semáforo; las tendencias con su intervalo
y el aviso correspondiente; los rankings con corrección por comparaciones
múltiples. El frontend puede decidir cómo enseñarlo, pero no puede alegar que no
lo sabía.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from nbastats.analysis.game_types import describe_game
from nbastats.analysis.reliability import analyze_splits, benjamini_hochberg
from nbastats.analysis.trends import (
    MIN_GAMES_FOR_TREND,
    TrendDirection,
    analyze_trend,
    rolling_mean,
)
from nbastats.api import queries as q
from nbastats.api.catalog import DIMENSIONS, STATS, Dimension, Stat
from nbastats.api.routers import teams as teams_router
from nbastats.api.schemas import (
    GameDetailOut,
    GameLogEntryOut,
    GameTypeOut,
    LeaderOut,
    LeadersResponse,
    PlayerBoxScoreOut,
    PlayerOut,
    PlayerRanksOut,
    PlayerSeasonOut,
    RankedStat,
    RecentGameOut,
    SplitOut,
    SplitsResponse,
    TeamBoxScoreOut,
    TrendOut,
)
from nbastats.db.session import get_db

app = FastAPI(
    title="Estadísticas NBA",
    description=(
        "Detección de patrones sobre 5 temporadas. Todas las respuestas de "
        "splits y tendencias incluyen tamaño de muestra e intervalo de "
        "confianza: consulta CAPABILITIES.md para saber qué preguntas admiten "
        "una respuesta sólida y cuáles no."
    ),
    version="0.1.0",
)

# El frontend de desarrollo (Vite) corre en otro puerto.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(teams_router.router)

SeasonsQuery = Query(None, description="Filtra por temporadas, ej. 2024-25")


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/catalog", tags=["meta"])
def catalog() -> dict:
    """Qué se puede pedir. El frontend construye sus menús con esto."""
    return {
        "stats": [
            {
                "value": s.value,
                "label": STATS[s].label,
                "is_rate": STATS[s].is_rate,
                "decimals": STATS[s].decimals,
            }
            for s in Stat
        ],
        "dimensions": [
            {
                "value": d.value,
                "label": DIMENSIONS[d].label,
                "levels": DIMENSIONS[d].typical_levels,
                "warning": DIMENSIONS[d].warning,
            }
            for d in Dimension
        ],
    }


# =========================================================================
# Jugadores
# =========================================================================


@app.get("/players", tags=["jugadores"])
def list_players(
    search: str = Query("", description="Búsqueda parcial por nombre"),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[dict]:
    return q.search_players(db, search, limit)


@app.get("/players/{player_id}", response_model=PlayerOut, tags=["jugadores"])
def get_player(player_id: int, db: Session = Depends(get_db)) -> PlayerOut:
    datos = q.get_player(db, player_id)
    if not datos:
        raise HTTPException(404, f"No existe el jugador {player_id}")
    return PlayerOut(**datos)


@app.get(
    "/players/{player_id}/seasons",
    response_model=list[PlayerSeasonOut],
    tags=["jugadores"],
)
def get_seasons(player_id: int, db: Session = Depends(get_db)) -> list[PlayerSeasonOut]:
    return [PlayerSeasonOut(**f) for f in q.get_player_seasons(db, player_id)]


@app.get(
    "/players/{player_id}/gamelog",
    response_model=list[GameLogEntryOut],
    tags=["jugadores"],
)
def get_gamelog(
    player_id: int,
    seasons: list[str] | None = SeasonsQuery,
    season_type: str = Query("regular", pattern="^(regular|playoffs|playin)$"),
    db: Session = Depends(get_db),
) -> list[GameLogEntryOut]:
    filas = q.get_gamelog(db, player_id, seasons, (season_type,))
    return [GameLogEntryOut(**f) for f in filas]


@app.get("/players/{player_id}/trend", response_model=TrendOut, tags=["análisis"])
def get_trend(
    player_id: int,
    stat: Stat = Query(Stat.PTS_36, description="Usa una TASA para detectar declive"),
    window: int = Query(25, ge=5, le=82, description="Ventana de la media móvil (solo dibujo)"),
    seasons: list[str] | None = SeasonsQuery,
    db: Session = Depends(get_db),
) -> TrendOut:
    """Tendencia de un jugador: ¿en declive, al alza o estable?

    La regresión se calcula sobre los valores CRUDOS, nunca sobre la media
    móvil: suavizar antes de regresar autocorrelaciona los puntos y hunde el
    p-valor artificialmente. `rolling` viaja aparte, solo para pintar.
    """
    jugador = q.get_player(db, player_id)
    if not jugador:
        raise HTTPException(404, f"No existe el jugador {player_id}")

    valores, fechas = q.get_stat_series(db, player_id, stat, seasons)
    resultado = analyze_trend(valores)

    return TrendOut.from_result(
        resultado,
        player_id=player_id,
        player_name=jugador["full_name"],
        stat=stat,
        stat_label=STATS[stat].label,
        series=valores,
        rolling=rolling_mean(valores, window) if valores else [],
        dates=fechas,
    )


@app.get("/players/{player_id}/splits", response_model=SplitsResponse, tags=["análisis"])
def get_splits(
    player_id: int,
    dimension: Dimension = Query(Dimension.HOME_AWAY),
    stat: Stat = Query(Stat.PTS_36),
    seasons: list[str] | None = SeasonsQuery,
    db: Session = Depends(get_db),
) -> SplitsResponse:
    """Rendimiento partido por una dimensión, con la incertidumbre incluida.

    Devuelve, por cada nivel: media cruda, media encogida hacia el promedio
    general del jugador, intervalo de confianza, tamaño de muestra y un valor q
    corregido por comparaciones múltiples.

    `value` es lo que conviene MOSTRAR: coincide con la media cruda cuando el
    split se distingue del resto, y con la encogida cuando no — que es la
    respuesta honesta ante una muestra pequeña.
    """
    jugador = q.get_player(db, player_id)
    if not jugador:
        raise HTTPException(404, f"No existe el jugador {player_id}")

    grupos = q.get_split_groups(db, player_id, stat, dimension, seasons)
    estimaciones = analyze_splits(grupos)
    salida = [SplitOut.from_estimate(e) for e in estimaciones.values()]

    aviso = DIMENSIONS[dimension].warning
    if not any(s.distinguishable for s in salida):
        aviso = (
            "Ningún nivel se distingue del resto tras corregir por comparaciones "
            "múltiples: aquí no hay patrón, solo variación normal. "
        ) + aviso

    return SplitsResponse(
        player_id=player_id,
        player_name=jugador["full_name"],
        stat=stat,
        stat_label=STATS[stat].label,
        dimension=dimension,
        dimension_label=DIMENSIONS[dimension].label,
        seasons=seasons or jugador.get("seasons", []),
        total_games=sum(len(v) for v in grupos.values()),
        splits=salida,
        caveat=aviso,
        any_distinguishable=any(s.distinguishable for s in salida),
    )


@app.get(
    "/players/{player_id}/recent",
    response_model=list[RecentGameOut],
    tags=["jugadores"],
)
def get_recent(
    player_id: int,
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[RecentGameOut]:
    """Los últimos partidos oficiales, con el tipo de cada uno.

    Incluye playoffs, play-in y NBA Cup: "sus últimos partidos" son los últimos
    que jugó. Filtrar a temporada regular escondería una eliminatoria entera.
    """
    salida = []
    for f in q.get_recent_games(db, player_id, limit):
        t = describe_game(f["season_type"], f.get("game_label"), f.get("game_sublabel"))
        salida.append(
            RecentGameOut(
                game_type=GameTypeOut(
                    key=t.key, label=t.label, is_postseason=t.is_postseason
                ),
                **{
                    k: v for k, v in f.items()
                    if k in RecentGameOut.model_fields and k != "game_type"
                },
            )
        )
    return salida


@app.get(
    "/players/{player_id}/ranks",
    response_model=PlayerRanksOut | None,
    tags=["jugadores"],
)
def get_ranks(
    player_id: int,
    season: str = Query(..., description="Temporada, ej. 2024-25"),
    db: Session = Depends(get_db),
) -> PlayerRanksOut | None:
    """Puesto del jugador en la liga, por estadística.

    Devuelve `null` si no llega al mínimo de partidos y minutos para entrar en
    el ranking. Eso es información, no un error: significa que compararlo con
    los titulares de la liga no tendría sentido.
    """
    fila = q.get_league_ranks(db, player_id, season)
    if not fila:
        return None

    def rk(valor_key: str, rank_key: str) -> RankedStat:
        v = fila.get(valor_key)
        return RankedStat(
            value=round(float(v), 4) if v is not None else None,
            rank=fila.get(rank_key),
        )

    return PlayerRanksOut(
        season_id=season,
        qualified_players=fila["qualified"],
        games_played=fila["gp"],
        pts=rk("ppg", "ppg_rank"),
        reb=rk("rpg", "rpg_rank"),
        ast=rk("apg", "apg_rank"),
        stl=rk("spg", "spg_rank"),
        blk=rk("bpg", "bpg_rank"),
        fg_pct=rk("fg_pct", "fg_pct_rank"),
        ts_pct=rk("ts_pct", "ts_pct_rank"),
    )


# =========================================================================
# Partidos
# =========================================================================


@app.get("/games/{game_id}", response_model=GameDetailOut, tags=["partidos"])
def get_game(game_id: str, db: Session = Depends(get_db)) -> GameDetailOut:
    """Todo lo que hay de un partido: los dos equipos y todos los jugadores.

    `game_id` va como TEXTO en la ruta, no como entero: los ids de la NBA
    llevan ceros a la izquierda ("0042500405") y codifican el tipo de partido
    en la tercera posición. Convertirlos a número los corrompe.
    """
    cabecera = q.get_game(db, game_id)
    if not cabecera:
        raise HTTPException(404, f"No existe el partido {game_id}")

    equipos = q.get_game_team_stats(db, game_id)
    if len(equipos) != 2:
        raise HTTPException(
            500, f"El partido {game_id} tiene {len(equipos)} equipos, se esperaban 2"
        )

    jugadores = q.get_game_player_stats(db, game_id)
    por_equipo: dict[int, list[PlayerBoxScoreOut]] = {}
    for j in jugadores:
        fila = PlayerBoxScoreOut(
            **{k: v for k, v in j.items() if k in PlayerBoxScoreOut.model_fields}
        )
        por_equipo.setdefault(j["team_id"], []).append(fila)

    def construir(datos: dict) -> TeamBoxScoreOut:
        return TeamBoxScoreOut(
            **{k: v for k, v in datos.items() if k in TeamBoxScoreOut.model_fields},
            players=por_equipo.get(datos["team_id"], []),
        )

    local = next(e for e in equipos if e["is_home"])
    visitante = next(e for e in equipos if not e["is_home"])

    t = describe_game(
        cabecera["season_type"], cabecera.get("game_label"), cabecera.get("game_sublabel")
    )

    return GameDetailOut(
        game_id=cabecera["game_id"],
        date=cabecera["date"],
        season_id=cabecera["season_id"],
        game_type=GameTypeOut(key=t.key, label=t.label, is_postseason=t.is_postseason),
        tipoff_utc=cabecera["tipoff_utc"],
        ot_periods=cabecera["ot_periods"] or 0,
        is_neutral_site=cabecera["is_neutral_site"],
        attendance=cabecera["attendance"],
        home=construir(local),
        away=construir(visitante),
    )


# =========================================================================
# Rankings
# =========================================================================


@app.get("/leaders/trending", response_model=LeadersResponse, tags=["análisis"])
def leaders_trending(
    direction: str = Query("declining", pattern="^(rising|declining)$"),
    stat: Stat = Query(Stat.PTS_36),
    min_games: int = Query(100, ge=MIN_GAMES_FOR_TREND, le=400),
    limit: int = Query(20, ge=1, le=100),
    seasons: list[str] | None = SeasonsQuery,
    db: Session = Depends(get_db),
) -> LeadersResponse:
    """Jugadores al alza o en declive, con control de falsos descubrimientos.

    Escanear ~600 jugadores a la vez son ~600 contrastes simultáneos: con
    α=0,05 saldrían ~30 "tendencias" por puro azar. Se aplica corrección de
    Benjamini-Hochberg sobre todos los p-valores y solo se devuelve lo que
    sobrevive.
    """
    series = q.get_all_player_series(db, stat, min_games, seasons)

    resultados = []
    for pid, (nombre, valores) in series.items():
        # Sin detección de puntos de cambio: es lo caro del análisis y aquí solo
        # interesa la pendiente. En la ficha individual sí se calcula.
        r = analyze_trend(valores, find_change_points=False)
        if r.direction is TrendDirection.INDETERMINADA:
            continue
        resultados.append((pid, nombre, valores, r))

    q_values = benjamini_hochberg([r.mk_p_value for *_, r in resultados])

    lideres = []
    for (pid, nombre, valores, r), qv in zip(resultados, q_values, strict=True):
        if qv >= 0.05:
            continue
        if direction == "rising" and r.slope_per_season <= 0:
            continue
        if direction == "declining" and r.slope_per_season >= 0:
            continue

        recientes = valores[-25:]
        lideres.append(
            LeaderOut(
                player_id=pid,
                player_name=nombre,
                n=r.n,
                slope_per_season=round(r.slope_per_season, 3),
                ci95_low=round(r.slope_ci95[0] * 82, 3),
                ci95_high=round(r.slope_ci95[1] * 82, 3),
                tau=round(r.tau, 3),
                q_value=round(qv, 5),
                direction=r.direction,
                reliability=r.reliability,
                current_value=round(sum(recientes) / len(recientes), 3)
                if recientes
                else None,
            )
        )

    lideres.sort(key=lambda x: x.slope_per_season, reverse=(direction == "rising"))

    return LeadersResponse(
        stat=stat,
        stat_label=STATS[stat].label,
        direction=direction,
        min_games=min_games,
        players_scanned=len(series),
        players_significant=len(lideres),
        caveat=(
            f"Se analizaron {len(series)} jugadores simultáneamente. Los valores q "
            "ya están corregidos por comparaciones múltiples (Benjamini-Hochberg); "
            "sin esa corrección aparecerían decenas de tendencias inexistentes."
        ),
        leaders=lideres[:limit],
    )
