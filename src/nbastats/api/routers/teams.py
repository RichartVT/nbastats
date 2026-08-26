"""Endpoints de equipo: ficha, historial, clasificación, enfrentamientos y análisis.

El análisis de equipo reutiliza `analyze_trend` y `analyze_splits` sin
modificarlos: esos módulos reciben listas de números y son indiferentes a si
vienen de un jugador o de una franquicia. Es la ventaja de haberlos escrito
sobre datos y no sobre entidades.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from nbastats.analysis.forecast import GameFeatures, model_from_params
from nbastats.analysis.game_types import describe_game
from nbastats.analysis.reliability import analyze_splits
from nbastats.analysis.trends import analyze_trend, rolling_mean
from nbastats.api import team_queries as tq
from nbastats.api.catalog import DIMENSIONS, Dimension
from nbastats.api.schemas import (
    GameTypeOut,
    HeadToHeadOut,
    RosterEntryOut,
    SplitOut,
    StandingOut,
    TeamGameOut,
    TeamOut,
    TeamSummaryOut,
)
from nbastats.db.session import get_db


def _norm_cdf(z: float) -> float:
    """Normal acumulada. Import diferido: `scipy` solo hace falta aquí."""
    from scipy import stats as _st

    return float(_st.norm.cdf(z))

router = APIRouter(tags=["equipos"])

SeasonQuery = Query(None, description="Temporada, ej. 2024-25. Vacío = la más reciente")


def _game_type(fila: dict) -> GameTypeOut:
    t = describe_game(
        fila.get("season_type", "regular"),
        fila.get("game_label"),
        fila.get("game_sublabel"),
    )
    return GameTypeOut(key=t.key, label=t.label, is_postseason=t.is_postseason)


def _to_team_game(fila: dict) -> TeamGameOut:
    return TeamGameOut(game_type=_game_type(fila), **{
        k: v for k, v in fila.items()
        if k in TeamGameOut.model_fields and k != "game_type"
    })


@router.get("/teams", response_model=list[TeamSummaryOut])
def list_teams(
    season: str | None = SeasonQuery, db: Session = Depends(get_db)
) -> list[TeamSummaryOut]:
    return [TeamSummaryOut(**f) for f in tq.list_teams(db, season)]


@router.get("/teams/{team_id}", response_model=TeamOut)
def get_team(
    team_id: int, season: str | None = SeasonQuery, db: Session = Depends(get_db)
) -> TeamOut:
    datos = tq.get_team(db, team_id, season)
    if not datos:
        raise HTTPException(404, f"No existe el equipo {team_id}")

    plantilla = [RosterEntryOut(**f) for f in tq.get_roster(db, team_id, season)]
    campos = {k: v for k, v in datos.items() if k in TeamOut.model_fields}
    campos["season_id"] = datos.get("standings_season")
    return TeamOut(**campos, roster=plantilla)


@router.get("/teams/{team_id}/games", response_model=list[TeamGameOut])
def get_team_games(
    team_id: int,
    seasons: list[str] | None = Query(None),
    limit: int | None = Query(None, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[TeamGameOut]:
    """Historial de partidos, del más reciente al más antiguo.

    Incluye playoffs y play-in: el calendario de un equipo es su temporada
    entera, no solo la fase regular.
    """
    return [_to_team_game(f) for f in tq.get_team_games(db, team_id, seasons, limit=limit)]


@router.get("/teams/{team_id}/roster", response_model=list[RosterEntryOut])
def get_roster(
    team_id: int, season: str | None = SeasonQuery, db: Session = Depends(get_db)
) -> list[RosterEntryOut]:
    return [RosterEntryOut(**f) for f in tq.get_roster(db, team_id, season)]


@router.get("/standings", response_model=list[StandingOut], tags=["clasificación"])
def get_standings(
    season: str | None = SeasonQuery, db: Session = Depends(get_db)
) -> list[StandingOut]:
    """Clasificación oficial, con los desempates de la NBA ya aplicados."""
    return [
        StandingOut(**{k: v for k, v in f.items() if k in StandingOut.model_fields})
        for f in tq.get_standings(db, season)
    ]


@router.get("/teams/{team_a}/vs/{team_b}", response_model=HeadToHeadOut)
def head_to_head(
    team_a: int,
    team_b: int,
    seasons: list[str] | None = Query(None),
    db: Session = Depends(get_db),
) -> HeadToHeadOut:
    """Enfrentamientos directos entre dos equipos."""
    a = tq.get_team(db, team_a)
    b = tq.get_team(db, team_b)
    if not a or not b:
        raise HTTPException(404, "Alguno de los dos equipos no existe")
    if team_a == team_b:
        raise HTTPException(400, "Un equipo no juega contra sí mismo")

    partidos = tq.get_head_to_head(db, team_a, team_b, seasons)
    victorias_a = sum(1 for p in partidos if p["won"])
    diffs = [p["point_diff"] for p in partidos if p["point_diff"] is not None]

    def resumen(datos: dict) -> TeamSummaryOut:
        return TeamSummaryOut(
            **{k: v for k, v in datos.items() if k in TeamSummaryOut.model_fields}
        )

    return HeadToHeadOut(
        team_a=resumen(a),
        team_b=resumen(b),
        seasons=sorted({p["season_id"] for p in partidos}),
        games_played=len(partidos),
        team_a_wins=victorias_a,
        team_b_wins=len(partidos) - victorias_a,
        avg_point_diff=round(sum(diffs) / len(diffs), 2) if diffs else None,
        games=[_to_team_game(p) for p in partidos],
    )


# =========================================================================
# Análisis de equipo
# =========================================================================


@router.get("/teams/{team_id}/trend", tags=["análisis"])
def team_trend(
    team_id: int,
    stat: str = Query("net_rating"),
    window: int = Query(15, ge=5, le=82),
    seasons: list[str] | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Tendencia de un equipo: ¿mejorando, empeorando o estable?

    La ventana por defecto es de 15 partidos y no de 25 como en jugadores: un
    equipo cambia de identidad con un traspaso o una lesión, así que una
    ventana larga suaviza justo lo que interesa ver.
    """
    if stat not in tq.TEAM_STATS:
        raise HTTPException(400, f"Estadística no válida: {stat}")

    equipo = tq.get_team(db, team_id)
    if not equipo:
        raise HTTPException(404, f"No existe el equipo {team_id}")

    valores, fechas = tq.get_team_series(db, team_id, stat, seasons)
    r = analyze_trend(valores)
    suave = rolling_mean(valores, window) if valores else []

    def limpio(x: float) -> float | None:
        return None if x != x else round(x, 4)

    return {
        "team_id": team_id,
        "team_name": equipo["full_name"],
        "stat": stat,
        "stat_label": tq.TEAM_STATS[stat][1],
        "n": r.n,
        "direction": r.direction.value,
        "reliability": r.reliability.value,
        "slope_per_season": limpio(r.slope_per_season),
        "ci95_low": limpio(r.slope_ci95[0] * 82),
        "ci95_high": limpio(r.slope_ci95[1] * 82),
        "r_squared": limpio(r.r_squared),
        "mk_p_value": limpio(r.mk_p_value),
        "tau": limpio(r.tau),
        "change_points": r.change_points,
        "note": r.note,
        "series": [round(v, 4) for v in valores],
        "rolling": [None if v is None else round(v, 4) for v in suave],
        "dates": [f.isoformat() for f in fechas],
    }


@router.get("/teams/{team_id}/splits", tags=["análisis"])
def team_splits(
    team_id: int,
    dimension: Dimension = Query(Dimension.HOME_AWAY),
    stat: str = Query("net_rating"),
    seasons: list[str] | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Rendimiento de un equipo partido por una dimensión, con incertidumbre.

    Misma garantía que en jugadores: nunca un número solo. Cada nivel viaja con
    su tamaño de muestra, intervalo y valor q corregido por FDR.
    """
    if stat not in tq.TEAM_STATS:
        raise HTTPException(400, f"Estadística no válida: {stat}")

    equipo = tq.get_team(db, team_id)
    if not equipo:
        raise HTTPException(404, f"No existe el equipo {team_id}")

    grupos = tq.get_team_split_groups(db, team_id, stat, dimension, seasons)
    salida = [SplitOut.from_estimate(e) for e in analyze_splits(grupos).values()]

    aviso = DIMENSIONS[dimension].warning
    if not any(s.distinguishable for s in salida):
        aviso = (
            "Ningún nivel se distingue del resto tras corregir por comparaciones "
            "múltiples: aquí no hay patrón, solo variación normal. "
        ) + aviso

    return {
        "team_id": team_id,
        "team_name": equipo["full_name"],
        "stat": stat,
        "stat_label": tq.TEAM_STATS[stat][1],
        "dimension": dimension.value,
        "dimension_label": DIMENSIONS[dimension].label,
        "total_games": sum(len(v) for v in grupos.values()),
        "splits": [s.model_dump() for s in salida],
        "caveat": aviso,
        "any_distinguishable": any(s.distinguishable for s in salida),
    }


@router.get("/team-catalog", tags=["meta"])
def team_catalog() -> dict:
    """Estadísticas de equipo consultables."""
    return {
        "stats": [
            {"value": clave, "label": etiqueta}
            for clave, (_, etiqueta) in tq.TEAM_STATS.items()
        ]
    }


# =========================================================================
# Fuerza de equipo y pronóstico
# =========================================================================


@router.get("/ratings", tags=["pronóstico"])
def ratings(season: str | None = Query(None), db: Session = Depends(get_db)) -> dict:
    """Los 30 equipos por fuerza, ajustada por la calidad de sus rivales.

    Un +5 de diferencial contra el calendario más duro y otro contra el más
    blando no valen lo mismo; esto los distingue y el diferencial de puntos no.
    """
    filas = tq.get_ratings(db, season)
    if not filas:
        raise HTTPException(404, "No hay ratings calculados. Corre `nbastats build-ratings`.")
    return {
        "season": filas[0]["season_id"],
        "home_advantage_margin": round(2 * float(filas[0]["home_advantage"]), 2),
        "league_mean": round(float(filas[0]["league_mean"]), 2),
        "note": (
            "Puntos por 100 posesiones respecto a la media de la liga. La defensa "
            "va en positivo: más alto es mejor. Los efectos de equipo están "
            "centrados en cero, así que la media de la liga la absorbe `league_mean`."
        ),
        "teams": [
            {
                "team_id": f["team_id"], "abbreviation": f["abbreviation"],
                "full_name": f["full_name"], "conference": f["conference"],
                "offense": round(float(f["offense"]), 2),
                "defense": round(float(f["defense"]), 2),
                "net": round(float(f["net"]), 2),
                "games": f["games"],
            }
            for f in filas
        ],
    }


@router.get("/predict", tags=["pronóstico"])
def predict(
    home: int = Query(..., description="Equipo local"),
    away: int = Query(..., description="Equipo visitante"),
    season: str | None = Query(None),
    neutral: bool = Query(False, description="Sede neutral: anula la localía"),
    rest_home: float = Query(1.0, ge=0, le=10),
    rest_away: float = Query(1.0, ge=0, le=10),
    b2b_home: bool = Query(False),
    b2b_away: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    """Probabilidad de victoria del local, con el desglose de dónde sale.

    Usa EXACTAMENTE el modelo que se validó: los coeficientes se leen de
    `model_runs` y se reconstruye el `WinModel`, en vez de reimplementar la
    fórmula aquí. Una versión anterior de este endpoint tenía su propia
    fórmula con dos multiplicadores escritos a mano, y calculaba algo distinto
    de lo que medía `/model/backtest` sin dar ningún error. Hay un test que
    exige que estos coeficientes reproduzcan las probabilidades guardadas.

    NO conoce las ausencias. Es el factor con más recorrido de todos los
    medidos —24 puntos porcentuales de diferencia en victorias entre jugar con
    la rotación entera y con 100+ minutos habituales fuera— y el modelo no lo
    ve. Va dicho en la respuesta, no en una nota al pie.
    """
    if home == away:
        raise HTTPException(400, "Un equipo no juega contra sí mismo.")

    rl = tq.get_rating(db, home, season)
    rv = tq.get_rating(db, away, season)
    if not rl or not rv:
        raise HTTPException(404, "Sin rating para alguno de los dos equipos.")

    fila = tq.get_model_run(db, season or rl["season_id"]) or tq.get_model_run(db)
    if not fila:
        raise HTTPException(404, "No hay modelo entrenado. Corre `nbastats build-ratings`.")

    modelo = model_from_params(
        fila["logit_params"], fila["margin_params"],
        float(fila["sigma"]), fila["train_games"],
    )
    variables = GameFeatures(
        rating_diff=float(rl["net"]) - float(rv["net"]),
        is_home_court=not neutral,
        rest_diff=min(rest_home, 4.0) - min(rest_away, 4.0),
        b2b_diff=(1.0 if b2b_away else 0.0) - (1.0 if b2b_home else 0.0),
    )

    # El desglose sale de los MISMOS coeficientes, multiplicando cada variable
    # por el suyo. Así la suma de las barras es el margen esperado por
    # construcción, y no una aproximación que pueda separarse de él.
    # Sin redondear: quien sume los componentes a mano debe obtener EXACTAMENTE
    # el margen esperado. El redondeo es cosa de la pantalla, no del contrato.
    c = modelo.margin_params
    componentes = [
        {
            "key": "rating", "label": "Diferencia de fuerza",
            "points": c["rating_diff"] * variables.rating_diff,
        },
        {
            "key": "home", "label": "Localía",
            # La localía vive en la constante: en el entrenamiento no había
            # sedes neutrales, así que la columna era constante y su efecto se
            # absorbió ahí. Ver el aviso sobre extrapolación más abajo.
            "points": 0.0 if neutral else c["const"],
        },
        {
            "key": "rest", "label": "Descanso",
            "points": c["rest_diff"] * variables.rest_diff,
        },
        {
            "key": "b2b", "label": "Segundo partido en 2 días",
            "points": c["b2b_diff"] * variables.b2b_diff,
        },
    ]

    margen = modelo.expected_margin(variables)
    if neutral:
        margen -= c["const"]
    sigma = modelo.sigma
    prob = modelo.probability(variables) if not neutral else float(
        _norm_cdf(margen / sigma) if sigma > 0 else 0.5
    )

    avisos = [
        f"El intervalo del margen es de ±{round(1.96 * sigma)} puntos. La varianza "
        "de un partido aplasta cualquier diferencia de plantilla: un 65% significa "
        "que ese equipo pierde uno de cada tres.",
        "No conoce ausencias, lesiones ni traspasos. Jugar sin la rotación habitual "
        "vale hasta 24 puntos porcentuales de probabilidad, y el modelo no lo ve.",
        "Calibrado solo sobre temporada regular. No usarlo para playoffs.",
    ]
    if neutral:
        avisos.append(
            "Sede neutral: el modelo se entrenó SIN partidos neutrales, así que "
            "aquí se le resta la localía por extrapolación. Con 14 partidos "
            "neutrales en cinco temporadas no hay muestra para comprobar que sea "
            "correcto anularla del todo."
        )
    if not modelo.agrees(variables):
        avisos.append(
            "Las dos rutas de cálculo —logística sobre el resultado y normal sobre "
            "el margen— discrepan más de 3 puntos porcentuales en este caso. La "
            "probabilidad mostrada es la media; tómala con reservas."
        )

    return {
        "home": {
            "team_id": home,
            "abbreviation": rl["abbreviation"],
            "net": round(float(rl["net"]), 2),
        },
        "away": {
            "team_id": away,
            "abbreviation": rv["abbreviation"],
            "net": round(float(rv["net"]), 2),
        },
        "season": rl["season_id"],
        "model_version": fila["model_version"],
        "fitted_at": fila["fitted_at"],
        "train_games": fila["train_games"],
        "home_win_prob": round(prob, 4),
        "prob_logit": round(modelo.probability_logit(variables), 4),
        "prob_margin": round(modelo.probability_margin(variables), 4),
        "expected_margin": margen,
        "margin_sigma": round(sigma, 2),
        "margin_ci95": [round(margen - 1.96 * sigma, 1), round(margen + 1.96 * sigma, 1)],
        "components": componentes,
        "warnings": avisos,
    }


@router.get("/model/backtest", tags=["pronóstico"])
def backtest(season: str | None = Query(None), db: Session = Depends(get_db)) -> dict:
    """Qué tal predice el modelo, medido fuera de muestra.

    Se publica salga como salga. La precisión sola no detecta un modelo roto:
    uno que acierta el 65% pero dice "80%" cuando gana el 60% tiene la misma
    precisión que uno bien calibrado y sus números no significan nada.
    """
    from nbastats.analysis.calibration import (
        brier,
        brier_skill_score,
        calibration_report,
        log_loss,
    )

    filas = tq.get_predictions(db, season)
    if not filas:
        raise HTTPException(404, "No hay predicciones. Corre `nbastats build-ratings`.")

    p = [float(f["home_win_prob"]) for f in filas]
    y = [bool(f["home_won"]) for f in filas]
    base = sum(y) / len(y)
    informe = calibration_report(p, y)
    desacuerdos = sum(
        1 for f in filas if abs(float(f["prob_logit"]) - float(f["prob_margin"])) > 0.03
    )

    return {
        "n": len(filas),
        "seasons": sorted({f["season_id"] for f in filas}),
        "accuracy": round(sum((a > 0.5) == b for a, b in zip(p, y, strict=True)) / len(p), 4),
        "brier": round(brier(p, y), 4),
        "log_loss": round(log_loss(p, y), 4),
        "brier_skill_score": round(brier_skill_score(p, y, base), 4),
        "baselines": {
            "always_home": round(base, 4),
            "always_home_brier": round(brier([base] * len(y), y), 4),
            "always_home_log_loss": round(log_loss([base] * len(y), y), 4),
            "better_record": 0.6464,
        },
        "calibration": {
            "slope": round(informe.slope, 3) if informe.slope else None,
            "intercept": round(informe.intercept, 3) if informe.intercept else None,
            "ece": round(informe.ece, 4),
            "ece_noise_floor": round(informe.ece_floor, 4),
            "within_noise": informe.within_noise,
            "note": informe.note,
            "bins": [
                {
                    "low": b.low, "high": b.high, "n": b.n,
                    "predicted": round(b.mean_predicted, 4),
                    "observed": round(b.observed, 4),
                    "ci95_low": round(b.ci95_low, 4),
                    "ci95_high": round(b.ci95_high, 4),
                    "calibrated": b.calibrated,
                }
                for b in informe.bins
            ],
        },
        "disagreements": desacuerdos,
        "caveat": (
            "La ventaja sobre 'gana el de mejor récord' es de +1,2 puntos "
            "porcentuales con p=0,083: real en el número, no concluyente al 5%. "
            "Lo que esa línea base no puede dar son probabilidades calibradas, "
            "que es donde está el valor de este modelo."
        ),
    }
