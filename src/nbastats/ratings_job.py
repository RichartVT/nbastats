"""Recalcular ratings, modelo y predicciones sobre lo que ya está cargado.

NO PIDE NADA A LA RED, y por eso no vive en `ingest/`, que es donde está todo lo
que habla con la NBA. Tampoco vive en `analysis/`, que es puro y no sabe que
existe una base de datos: este módulo es exactamente la costura entre los dos —
lee filas, llama a los motores, escribe filas.

Estaba embebido en `cli.py` con su SQL dentro, ~120 líneas, mientras todos los
demás comandos delegan en un módulo. Sacarlo no es solo orden: `daily` necesita
llamarlo, y un comando de Typer no se puede invocar limpiamente desde otro.

POR QUÉ `daily` TIENE QUE LLAMARLO. Las consultas resuelven la temporada con
`COALESCE(:season, MAX(...))`, sin ninguna marca de obsolescencia. Si esto no se
reajusta al entrar una temporada nueva, `/ratings` y `/predict` seguirán
sirviendo la anterior **como si fuera la actual**, sin error y sin aviso.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import text

from nbastats.analysis.backtest import MODEL_VERSION, GameRow, evaluate, walk_forward
from nbastats.analysis.calibration import (
    brier,
    brier_skill_score,
    calibration_report,
    log_loss,
)
from nbastats.db.models import GamePrediction, ModelRun, TeamSeasonRating
from nbastats.db.session import session_scope
from nbastats.ingest.bulk import upsert

logger = logging.getLogger(__name__)

# Se excluyen las sedes neutrales: la localía es una variable del modelo y en
# sede neutral no aplica, así que mezclarlas contaminaría su coeficiente.
CONSULTA_PARTIDOS = text("""
    SELECT g.game_id, g.season_id, g.game_date_local AS fecha,
           g.home_team_id, g.away_team_id,
           h.won AS gano_local, h.plus_minus AS margen,
           100.0*h.pts/NULLIF(h.possessions,0) AS local_100,
           100.0*a.pts/NULLIF(a.possessions,0) AS visitante_100,
           h.rest_days AS desc_local, a.rest_days AS desc_visitante,
           h.is_back_to_back AS b2b_local, a.is_back_to_back AS b2b_visitante
    FROM games g
    JOIN team_game_stats h ON h.game_id = g.game_id AND h.team_id = g.home_team_id
    JOIN team_game_stats a ON a.game_id = g.game_id AND a.team_id = g.away_team_id
    WHERE g.season_type = 'regular' AND NOT g.is_neutral_site
    ORDER BY g.game_date_local, g.game_id
""")


def _cargar() -> list[GameRow]:
    with session_scope() as s:
        filas = s.execute(CONSULTA_PARTIDOS).mappings().all()
    return [
        GameRow(
            game_id=f["game_id"], season_id=f["season_id"], date=f["fecha"],
            home_id=f["home_team_id"], away_id=f["away_team_id"],
            home_won=bool(f["gano_local"]), margin=float(f["margen"] or 0),
            home_pts_per_100=float(f["local_100"]) if f["local_100"] else None,
            away_pts_per_100=float(f["visitante_100"]) if f["visitante_100"] else None,
            home_rest=float(f["desc_local"] or 0),
            away_rest=float(f["desc_visitante"] or 0),
            home_b2b=bool(f["b2b_local"]), away_b2b=bool(f["b2b_visitante"]),
        )
        for f in filas
    ]


def rebuild_ratings() -> dict:
    """Reajusta ratings, modelos y predicciones, y los guarda.

    Devuelve las métricas para que quien llame decida cómo enseñarlas. Es
    idempotente: sobre los mismos datos produce exactamente los mismos números.
    """
    partidos = _cargar()
    if not partidos:
        return {"partidos": 0, "temporadas": 0, "modelos": 0, "predicciones": 0}

    muestras, finales = walk_forward(partidos)
    predicciones, modelos = evaluate(muestras)
    ahora = dt.datetime.now(dt.UTC)

    with session_scope() as sesion:
        upsert(sesion, TeamSeasonRating, [
            {
                "season_id": season, "team_id": tid,
                "offense": round(r.offense, 3), "defense": round(r.defense, 3),
                "net": round(r.net, 3), "games": r.games,
                "home_advantage": round(m.home_advantage, 3),
                "league_mean": round(m.league_mean, 3),
            }
            for season, m in finales.items() for tid, r in m.ratings.items()
        ], keys=["season_id", "team_id"])

        # Los coeficientes ajustados. Sin esto el simulador no tiene de dónde
        # leerlos y acaba inventándoselos, que es lo que pasó en la fase 17.
        upsert(sesion, ModelRun, [
            {
                "model_version": MODEL_VERSION, "season_id": season,
                "logit_params": m.logit_params, "margin_params": m.margin_params,
                "sigma": round(m.sigma, 4), "train_games": m.n_train,
                "fitted_at": ahora,
            }
            for season, m in modelos.items()
        ], keys=["model_version", "season_id"])

        upsert(sesion, GamePrediction, [
            {
                "game_id": p.game_id, "model_version": MODEL_VERSION,
                "home_win_prob": round(p.prob, 4),
                "expected_margin": round(p.expected_margin, 3),
                "margin_sigma": round(p.sigma, 3),
                "rating_diff": round(p.features.rating_diff, 3),
                "rest_diff": round(p.features.rest_diff, 3),
                "b2b_diff": round(p.features.b2b_diff, 3),
                "prob_logit": round(p.prob_logit, 4),
                "prob_margin": round(p.prob_margin, 4),
                "train_games": p.train_games, "fitted_at": ahora,
            }
            for p in predicciones
        ], keys=["game_id", "model_version"])

        # BORRAR LO QUE YA NO SE PRODUCE. `upsert` escribe y actualiza, pero no
        # borra: una fila que deja de generarse se queda ahí para siempre.
        #
        # No es hipotético. La primera vez que `daily` corrió entero, `enrich`
        # marcó como sede neutral cuatro partidos de 2023-24 —las semifinales de
        # la Copa NBA en Las Vegas, el de París y el de México— que el modelo
        # excluye a propósito. Sus predicciones viejas siguieron en la tabla, y
        # `/model/backtest` las habría contado con coeficientes de otra corrida.
        #
        # Todo lo escrito en esta pasada comparte `fitted_at`, así que lo
        # anterior a ella es exactamente lo que sobra.
        for tabla in ("game_predictions", "model_runs"):
            borradas = sesion.execute(
                text(f"DELETE FROM {tabla} WHERE model_version = :v AND fitted_at < :t"),
                {"v": MODEL_VERSION, "t": ahora},
            ).rowcount
            if borradas:
                logger.info("%s: %d filas obsoletas borradas", tabla, borradas)

    probs = [p.prob for p in predicciones]
    reales = [p.home_won for p in predicciones]
    base = sum(reales) / len(reales)
    acierto = sum((p > 0.5) == r for p, r in zip(probs, reales, strict=True)) / len(probs)
    inf = calibration_report(probs, reales)

    return {
        "partidos": len(partidos),
        "temporadas": len(finales),
        "modelos": len(modelos),
        "predicciones": len(predicciones),
        "fitted_at": ahora,
        "acierto": acierto,
        "brier": brier(probs, reales),
        "log_loss": log_loss(probs, reales),
        "bss": brier_skill_score(probs, reales, base),
        "ece": inf.ece,
        "ece_floor": inf.ece_floor,
        "slope": inf.slope,
        "within_noise": inf.within_noise,
    }
