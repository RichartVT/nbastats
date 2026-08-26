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

from nbastats.analysis.absences import describe_absences
from nbastats.analysis.expected import (
    ShootingNorms,
    TeamBox,
    attribute_margin,
    four_factors,
    shrunk_norm,
)
from nbastats.analysis.game_types import describe_game
from nbastats.analysis.player_status import describe_status
from nbastats.analysis.reliability import (
    analyze_splits,
    benjamini_hochberg,
    reliability_for,
)
from nbastats.analysis.stability import K_HABILIDAD, K_MIXTO, variance_components
from nbastats.analysis.trends import (
    MIN_GAMES_FOR_TREND,
    TrendDirection,
    analyze_trend,
    rolling_mean,
)
from nbastats.api import queries as q
from nbastats.api.catalog import (
    DIMENSIONS,
    MAX_CRITERIOS_ORDEN,
    MIN_FG3A_AUTO,
    MIN_FG3A_OPTIONS,
    MIN_GAMES_OPTIONS,
    MIN_TSA_AUTO,
    MIN_TSA_OPTIONS,
    PLAYER_SORT_LABELS,
    PLAYER_STATUS_LABELS,
    POSITIONS,
    STATS,
    STATS_POR_CUARTO,
    Dimension,
    PlayerSort,
    PlayerStatusFilter,
    PositionGroup,
    SortDir,
    Stat,
    parse_sort,
)
from nbastats.api.routers import teams as teams_router
from nbastats.api.schemas import (
    AbsenceIndexOut,
    AbsentPlayerOut,
    GameDetailOut,
    GameExpectedOut,
    GameLogEntryOut,
    GameTypeOut,
    LeaderOut,
    LeadersResponse,
    OfficialOut,
    PeriodScoreOut,
    PlayerBoxScoreOut,
    PlayerListItemOut,
    PlayerListResponse,
    PlayerOut,
    PlayerRanksOut,
    PlayerSeasonOut,
    PlayerStatusOut,
    RankedStat,
    RecentGameOut,
    SplitOut,
    SplitsResponse,
    StabilityOut,
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
def catalog(db: Session = Depends(get_db)) -> dict:
    """Qué se puede pedir. El frontend construye sus menús con esto.

    Las temporadas salen de los datos cargados, no de una constante: una lista
    escrita a mano en el frontend se queda desfasada en cuanto entra una
    temporada nueva, y nadie se acuerda de tocarla.
    """
    return {
        "seasons": q.list_seasons(db),
        "counts": q.dataset_counts(db),
        "player_filters": {
            "statuses": [
                {"value": s.value, "label": PLAYER_STATUS_LABELS[s]}
                for s in PlayerStatusFilter
            ],
            "positions": [
                {"value": p.value, "label": POSITIONS[p].label} for p in PositionGroup
            ],
            "sorts": [
                {"value": s.value, "label": PLAYER_SORT_LABELS[s]} for s in PlayerSort
            ],
            "min_games": [{"value": v, "label": t} for v, t in MIN_GAMES_OPTIONS],
            "min_fg3a": [{"value": v, "label": t} for v, t in MIN_FG3A_OPTIONS],
            "min_fg3a_auto": MIN_FG3A_AUTO,
            "min_tsa": [{"value": v, "label": t} for v, t in MIN_TSA_OPTIONS],
            "min_tsa_auto": MIN_TSA_AUTO,
            "countries": q.list_countries(db),
        },
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


@app.get("/players", response_model=PlayerListResponse, tags=["jugadores"])
def list_players(
    search: str = Query("", description="Búsqueda parcial por nombre, sin acentos"),
    status: PlayerStatusFilter | None = Query(None, description="Situación del jugador"),
    team_id: int | None = Query(
        None,
        description=(
            "Equipo actual. Para quien no está en plantilla es el último "
            "equipo conocido, así que el filtro devuelve también a sus exjugadores."
        ),
    ),
    position: PositionGroup | None = Query(None),
    season: str | None = Query(
        None,
        pattern=r"^\d{4}-\d{2}$",
        description="Limita los promedios y los partidos a esta temporada",
    ),
    min_games: int = Query(0, ge=0, le=500, description="Suelo de partidos en el alcance"),
    min_fg3a: float | None = Query(
        None,
        ge=0,
        description=(
            "Suelo de triples LANZADOS en el alcance (totales, no por partido: la "
            "precisión de un porcentaje depende del número de intentos). Omitirlo "
            f"NO significa cero, significa 'decide tú': la API pone {MIN_FG3A_AUTO:.0f} "
            "cuando se ordena por % de triples. Para no filtrar nada, min_fg3a=0."
        ),
    ),
    min_tsa: float | None = Query(
        None,
        ge=0,
        description=(
            "Suelo de intentos de tiro verdaderos (fga + 0,44·fta) en el alcance. "
            f"Igual que min_fg3a: omitirlo deja que la API ponga {MIN_TSA_AUTO:.0f} "
            "cuando se ordena por TS%."
        ),
    ),
    country: str | None = Query(
        None,
        max_length=60,
        description="País de la ficha oficial, tal cual lo escribe la NBA: 'USA', 'Serbia'",
    ),
    sort: str = Query(
        PlayerSort.PARTIDOS.value,
        description=(
            "Uno o varios criterios separados por comas, cada uno "
            "'clave' o 'clave:asc|desc'. Ej: 'edad:desc,puntos:asc'. "
            f"Se aplican como máximo {MAX_CRITERIOS_ORDEN}."
        ),
    ),
    direction: SortDir = Query(
        SortDir.DESC,
        alias="dir",
        description="Dirección para los criterios que no la lleven escrita",
    ),
    # El tope da para la plantilla entera (1.030 jugadores en 5 temporadas):
    # la consulta agrega una vista de ~8.000 filas y tarda decenas de
    # milisegundos, así que paginar por obligación no compraría nada.
    limit: int = Query(50, ge=1, le=1500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> PlayerListResponse:
    """Listado de jugadores con su situación, su equipo y sus promedios.

    El estado NO es un campo de la base: la NBA solo publica Active/Inactive,
    que no distingue al que se quedó sin equipo en verano del que lleva tres
    años fuera. Se deriva cruzándolo con la última temporada en la que jugó
    (ver `analysis.player_status`).

    Los promedios corresponden al alcance pedido: con `season` son los de esa
    temporada, sin él los de las cinco cargadas.
    """
    try:
        criterios = parse_sort(sort, direction.value)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    # Omitido no es cero: es "decide tú". Solo entonces entra el suelo
    # automático, y únicamente si ese porcentaje participa en el orden.
    ordenado_por = {c for c, _ in criterios}

    auto3 = min_fg3a is None and PlayerSort.TRIPLES.value in ordenado_por
    suelo_triples = MIN_FG3A_AUTO if auto3 else (min_fg3a or 0.0)

    auto_ts = min_tsa is None and PlayerSort.TS.value in ordenado_por
    suelo_tsa = MIN_TSA_AUTO if auto_ts else (min_tsa or 0.0)

    datos = q.search_players(
        db,
        search,
        limit,
        offset=offset,
        status=status.value if status else None,
        team_id=team_id,
        position=POSITIONS[position].db_word if position else None,
        season=season,
        min_games=min_games,
        country=country,
        min_fg3a=suelo_triples,
        min_tsa=suelo_tsa,
        criterios=criterios,
    )

    items = []
    for f in datos["items"]:
        estado = describe_status(
            f["roster_status"],
            f["ultima_nba"],
            datos["latest_season"],
            f["current_team_name"],
        )
        items.append(
            PlayerListItemOut(
                status=PlayerStatusOut(
                    key=estado.key,
                    label=estado.label,
                    note=estado.note,
                    on_roster=estado.on_roster,
                    team_label=estado.team_label,
                ),
                **{k: v for k, v in f.items() if k in PlayerListItemOut.model_fields},
            )
        )

    return PlayerListResponse(
        total=datos["total"],
        shown=len(items),
        latest_season=datos["latest_season"],
        season=season,
        min_fg3a_applied=suelo_triples,
        min_fg3a_auto=auto3,
        min_tsa_applied=suelo_tsa,
        min_tsa_auto=auto_ts,
        items=items,
    )


@app.get("/players/{player_id}", response_model=PlayerOut, tags=["jugadores"])
def get_player(player_id: int, db: Session = Depends(get_db)) -> PlayerOut:
    datos = q.get_player(db, player_id)
    if not datos:
        raise HTTPException(404, f"No existe el jugador {player_id}")

    temporadas = datos.get("seasons") or []
    estado = describe_status(
        datos.get("roster_status"),
        temporadas[-1] if temporadas else None,
        q.latest_season(db),
        datos.get("current_team_name"),
    )
    return PlayerOut(
        **datos,
        status=PlayerStatusOut(
            key=estado.key,
            label=estado.label,
            note=estado.note,
            on_roster=estado.on_roster,
            team_label=estado.team_label,
        ),
    )


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

    # Por cuarto no hay tasas, y no es un hueco: extrapolar a 36 minutos desde
    # los 4 que alguien jugó en un tercer cuarto da un número sin sentido. Se
    # rechaza la petición en vez de devolver nulos.
    if dimension is Dimension.PERIOD and stat not in STATS_POR_CUARTO:
        raise HTTPException(
            422,
            f"'{stat.value}' es una tasa y no existe por cuarto. "
            f"Válidas: {', '.join(s.value for s in STATS_POR_CUARTO)}",
        )

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
    cuartos = q.get_game_player_periods(db, game_id)
    ausencias = q.get_game_absences(db, game_id)
    por_equipo: dict[int, list[PlayerBoxScoreOut]] = {}
    for j in jugadores:
        fila = PlayerBoxScoreOut(
            points_by_period=cuartos.get(j["player_id"], {}),
            **{k: v for k, v in j.items() if k in PlayerBoxScoreOut.model_fields},
        )
        por_equipo.setdefault(j["team_id"], []).append(fila)

    def construir(datos: dict) -> TeamBoxScoreOut:
        # El índice se deriva en `analysis`, no aquí: la API pasa los números y
        # recibe el nivel y la etiqueta ya decididos, como con la situación del
        # jugador. Los nombres de los ausentes vienen de su propia consulta.
        idx = describe_absences(datos.get("absent_minutes"), datos.get("absent_players"))
        return TeamBoxScoreOut(
            **{k: v for k, v in datos.items() if k in TeamBoxScoreOut.model_fields},
            players=por_equipo.get(datos["team_id"], []),
            absences=AbsenceIndexOut(
                minutes=idx.minutes, players=idx.players, level=idx.level,
                label=idx.label, margin_cost=round(idx.margin_cost, 2),
                absent=[AbsentPlayerOut(**a) for a in ausencias.get(datos["team_id"], [])],
            ),
        )

    local = next(e for e in equipos if e["is_home"])
    visitante = next(e for e in equipos if not e["is_home"])

    t = describe_game(
        cabecera["season_type"], cabecera.get("game_label"), cabecera.get("game_sublabel")
    )

    return GameDetailOut(
        periods=[PeriodScoreOut(**p) for p in q.get_game_periods(db, game_id)],
        officials=[OfficialOut(**o) for o in q.get_game_officials(db, game_id)],
        arena_name=cabecera["arena_name"],
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


# Cuántos intentos hacen falta para que el acierto propio de un equipo pese lo
# mismo que el de la liga. Es la `k` de `stability.py` contada en intentos: el
# acierto de 2 tiene k=16 partidos y un equipo tira ~60 dobles por partido, de
# donde salen ~950; el triple es mucho más ruidoso (k=150) y su prior es
# proporcionalmente mayor. Sin esto, un equipo de 20 triples lanzados tendría
# una "norma" que es puro ruido.
_PRIOR_INTENTOS = {"fg2": 950.0, "fg3": 1400.0, "ft": 400.0}


@app.get("/games/{game_id}/expected", response_model=GameExpectedOut, tags=["partido"])
def get_game_expected(game_id: str, db: Session = Depends(get_db)) -> dict:
    """De dónde salieron los puntos: volumen contra acierto.

    QUÉ ES Y QUÉ NO ES. Es aritmética exacta: se mantiene el volumen de tiro
    —cuántos triples se tiran y cuántos se conceden, que es decisión y se mide
    como lo más estable del juego— y se sustituye solo el ACIERTO por la norma
    del equipo. Cada término es lineal, así que la suma de los componentes ES la
    diferencia entre el margen real y el esperado, sin residuo.

    **No dice quién merecía ganar.** Esa afirmación se probó en la fase 13 y no
    sobrevivió: el margen esperado no predice la fuerza de un equipo mejor que
    el margen real, así que el veredicto no se publica. Lo que se publica es el
    reparto, que sí es verificable a mano.

    Y los componentes se cancelan entre sí —quien tira mucho de tres genera
    menos rebote ofensivo—, así que una barra suelta NO es un contrafactual: no
    se puede leer como "sin eso habrían ganado por 8".
    """
    datos = q.get_game_expected_inputs(db, game_id)
    if not datos:
        raise HTTPException(status_code=404, detail="Partido no encontrado")

    liga = datos["league"]
    normas_liga = ShootingNorms(
        fg2_pct=_pct(liga["fgm"] - liga["fg3m"], liga["fga"] - liga["fg3a"]),
        fg3_pct=_pct(liga["fg3m"], liga["fg3a"]),
        ft_pct=_pct(liga["ftm"], liga["fta"]),
        n_games=0,
    )

    def caja(tid: int) -> TeamBox:
        b = datos["boxes"][tid]
        return TeamBox(
            pts=b["pts"], fgm=b["fgm"], fga=b["fga"], fg3m=b["fg3m"], fg3a=b["fg3a"],
            ftm=b["ftm"], fta=b["fta"], oreb=b["oreb"], dreb=b["dreb"], tov=b["tov"],
        )

    def normas(tid: int) -> ShootingNorms:
        """La norma del equipo, encogida hacia la liga por su fiabilidad."""
        t = datos["season_totals"].get(tid)
        if not t or not t["n_games"]:
            return normas_liga
        return ShootingNorms(
            fg2_pct=shrunk_norm(
                t["fgm"] - t["fg3m"], t["fga"] - t["fg3a"],
                normas_liga.fg2_pct, _PRIOR_INTENTOS["fg2"],
            ),
            fg3_pct=shrunk_norm(
                t["fg3m"], t["fg3a"], normas_liga.fg3_pct, _PRIOR_INTENTOS["fg3"]
            ),
            ft_pct=shrunk_norm(
                t["ftm"], t["fta"], normas_liga.ft_pct, _PRIOR_INTENTOS["ft"]
            ),
            n_games=int(t["n_games"]),
        )

    local_id, visitante_id = datos["home_team_id"], datos["away_team_id"]
    caja_local, caja_visitante = caja(local_id), caja(visitante_id)
    n_local, n_visitante = normas(local_id), normas(visitante_id)

    atr = attribute_margin(caja_local, n_local, caja_visitante, n_visitante)
    ff_local = four_factors(caja_local, caja_visitante)
    ff_visitante = four_factors(caja_visitante, caja_local)
    # La norma sale de la temporada del equipo, así que su fiabilidad es la del
    # equipo con menos partidos: una norma de 6 partidos y otra de 70 se
    # escriben igual y no valen lo mismo.
    n_norma = min(n_local.n_games, n_visitante.n_games)
    fiab = reliability_for(n_norma)

    def lado(tid: int, luck, norm: ShootingNorms, ff) -> dict:
        b = datos["boxes"][tid]
        return {
            "team_id": tid,
            "abbreviation": b["abbreviation"],
            "full_name": b["full_name"],
            "actual_points": luck.actual_points,
            "expected_points": round(luck.expected_points, 2),
            "luck_points": round(luck.total, 2),
            "norms": {
                "fg2_pct": round(norm.fg2_pct, 4),
                "fg3_pct": round(norm.fg3_pct, 4),
                "ft_pct": round(norm.ft_pct, 4),
                "n_games": norm.n_games,
            },
            "four_factors": {
                "efg_pct": _redondea(ff.efg_pct, 4),
                "tov_rate": _redondea(ff.tov_rate, 4),
                "oreb_pct": _redondea(ff.oreb_pct, 4),
                "ft_rate": _redondea(ff.ft_rate, 4),
                "possessions": round(ff.possessions, 1),
            },
        }

    return {
        "game_id": game_id,
        "season_id": datos["season_id"],
        "actual_margin": atr.actual_margin,
        "expected_margin": round(atr.expected_margin, 2),
        "swing": round(atr.swing, 2),
        # Debe ser 0. Se devuelve para que un fallo de atribución no viva en
        # silencio: si algún día no es 0, el desglose dejó de cerrar.
        "unexplained_pts": round(atr.unexplained_pts, 10),
        "components": [
            {"key": c.key, "label": c.label, "points": round(c.points, 2), "detail": c.detail}
            for c in atr.components
        ],
        "home": lado(local_id, atr.home, n_local, ff_local),
        "away": lado(visitante_id, atr.away, n_visitante, ff_visitante),
        "reliability": {"level": fiab.value, "n_games": n_norma},
        "note": (
            "Se mantiene el volumen de tiro y se sustituye solo el acierto por la "
            "norma del equipo, calculada SIN este partido. La suma de los "
            "componentes es exactamente la diferencia entre el margen real y el "
            "esperado. NO dice quién merecía ganar: esa afirmación se probó y no "
            "sobrevivió. Y los componentes se compensan entre sí, así que una "
            "barra suelta no es un contrafactual."
        ),
    }


def _pct(hechos: int | None, intentos: int | None) -> float:
    return (hechos or 0) / intentos if intentos else 0.0


def _redondea(v: float | None, n: int) -> float | None:
    return None if v is None else round(v, n)


# Qué se descompone, y cómo se calcula cada cosa por partido.
#
# EL PAR QUE JUSTIFICA TODA LA TABLA: "triples que concedes" contra "que esos
# triples entren". El primero es decisión tuya y se estabiliza enseguida; el
# segundo es la noche. Sin medirlo, cualquiera podría afirmar lo contrario con
# la misma seguridad.
_COMPONENTES: dict[str, tuple[str, str]] = {
    "fg3a": ("Triples que tiras", "volumen"),
    "opp_fg3a": ("Triples que concedes", "volumen"),
    "fg3_pct": ("Acierto en triples", "acierto"),
    "opp_fg3_pct": ("Acierto en los triples que concedes", "acierto"),
    "efg_pct": ("eFG% propio", "acierto"),
    "opp_efg_pct": ("eFG% concedido", "acierto"),
    "tov_rate": ("Pérdidas por posesión", "control"),
    "oreb_pct": ("% de rebote ofensivo", "control"),
    "ft_rate": ("Tiros libres por tiro de campo", "control"),
    "pace": ("Ritmo", "control"),
    "pts_paint": ("Puntos en la pintura", "origen"),
    "pts_fastbreak": ("Puntos de contraataque", "origen"),
    "pts_off_turnovers": ("Puntos tras pérdida", "origen"),
    "pts_2nd_chance": ("Puntos de segunda oportunidad", "origen"),
}


def _valor(f: dict, clave: str) -> float | None:
    """Un componente de una fila equipo-partido. `None` si no se puede calcular."""
    def div(a, b):
        a, b = (a or 0), (b or 0)
        return a / b if b else None

    if clave == "fg3_pct":
        return div(f["fg3m"], f["fg3a"])
    if clave == "opp_fg3_pct":
        return div(f["opp_fg3m"], f["opp_fg3a"])
    if clave == "efg_pct":
        fga = f["fga"] or 0
        return ((f["fgm"] or 0) + 0.5 * (f["fg3m"] or 0)) / fga if fga else None
    if clave == "opp_efg_pct":
        fga = f["opp_fga"] or 0
        return ((f["opp_fgm"] or 0) + 0.5 * (f["opp_fg3m"] or 0)) / fga if fga else None
    if clave == "tov_rate":
        poss = (f["fga"] or 0) - (f["oreb"] or 0) + (f["tov"] or 0) + 0.44 * (f["fta"] or 0)
        return div(f["tov"], poss)
    if clave == "oreb_pct":
        return div(f["oreb"], (f["oreb"] or 0) + (f["opp_dreb"] or 0))
    if clave == "ft_rate":
        return div(f["fta"], f["fga"])
    v = f.get(clave)
    return None if v is None else float(v)


@app.get("/stability", response_model=StabilityOut, tags=["análisis"])
def get_stability(
    season: str | None = Query(None, description="Vacío = todas las cargadas"),
    db: Session = Depends(get_db),
) -> dict:
    """Cuántos partidos hacen falta para creerse el dato de un equipo.

    `k` es el número de partidos en que la media propia de un equipo pasa a
    pesar la mitad, y la otra mitad se la lleva la liga. Sale de descomponer la
    varianza —cuánta diferencia REAL hay entre equipos, una vez descontado el
    ruido de muestreo— con el mismo método de los momentos que sostiene el
    encogimiento de los splits.

    Es la tabla que decide qué es habilidad y qué es la noche, y de la que
    depende el motor de resultado esperado: por eso se publica en vez de quedar
    como constante escondida. El plan original DABA POR SENTADO qué componentes
    eran suerte; esto lo mide.
    """
    filas = q.get_team_game_series(db, season)
    if not filas:
        raise HTTPException(status_code=404, detail="Sin datos para esa temporada")

    salida = []
    for clave, (etiqueta, familia) in _COMPONENTES.items():
        grupos: dict[str, list[float]] = {}
        for f in filas:
            v = _valor(f, clave)
            if v is not None:
                grupos.setdefault(f"{f['team_id']}|{f['season_id']}", []).append(v)
        grupos = {u: vs for u, vs in grupos.items() if len(vs) >= 2}
        if len(grupos) < 2:
            continue
        vc = variance_components(grupos, label=etiqueta)
        salida.append(
            {
                "key": clave,
                "label": etiqueta,
                "family": familia,
                "k_games": None if vc.k_games is None else round(vc.k_games, 1),
                "stability": vc.stability.key,
                "stability_label": vc.stability.label,
                "note": vc.stability.note,
                "reliability": vc.reliability.value,
                "n_units": vc.n_units,
                "mean_games": round(vc.mean_n, 1),
                "tau_squared": vc.tau_squared,
                "within_var": vc.within_var,
                # Peso que merece la media propia con media temporada y con una
                # entera: es la lectura práctica de `k`.
                "weight_41": round(vc.weight(41), 3),
                "weight_82": round(vc.weight(82), 3),
            }
        )

    # De lo más estable a lo más ruidoso. `k=None` (sin señal detectable) al
    # final: no es "muy estable", es "no se distingue nada".
    salida.sort(key=lambda x: (x["k_games"] is None, x["k_games"] or 0))
    return {
        "season": season,
        "components": salida,
        "boundaries": {"skill_max_k": K_HABILIDAD, "mixed_max_k": K_MIXTO},
        "note": (
            "k = partidos para que la media propia de un equipo pese la mitad. "
            "Por debajo de 41 (media temporada) es habilidad; por encima de 82 "
            "(temporada entera) es sobre todo azar. Se mide descontando el ruido "
            "de muestreo, no comparando dispersiones en bruto."
        ),
    }
