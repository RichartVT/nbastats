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

from nbastats.analysis.reliability import analyze_splits, benjamini_hochberg
from nbastats.analysis.trends import (
    MIN_GAMES_FOR_TREND,
    TrendDirection,
    analyze_trend,
    rolling_mean,
)
from nbastats.api import queries as q
from nbastats.api.catalog import DIMENSIONS, STATS, Dimension, Stat
from nbastats.api.schemas import (
    GameLogEntryOut,
    LeaderOut,
    LeadersResponse,
    PlayerOut,
    PlayerSeasonOut,
    SplitOut,
    SplitsResponse,
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
