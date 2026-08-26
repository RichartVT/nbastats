"""Cálculo walk-forward de ratings y predicciones, para persistirlo.

Vive en `analysis/` y no en `api/` porque es cálculo, no consulta — pero a
diferencia del resto del paquete sí necesita hablar con la base, así que recibe
las filas ya leídas y devuelve las filas a escribir. La E/S se queda fuera.

EL ORDEN IMPORTA Y ES LO ÚNICO QUE PUEDE ROMPERSE EN SILENCIO:

1. Los ratings de un partido se ajustan SOLO con partidos de fecha anterior.
   Los del mismo día no se ven entre sí, porque en la realidad tampoco.
2. El modelo de probabilidad se entrena SOLO con temporadas anteriores.
3. La primera temporada no se puntúa: no tiene con qué entrenarse.

Si cualquiera de los tres se relaja, las métricas suben y dejan de significar
nada. No dan error: simplemente mienten.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from nbastats.analysis.forecast import GameFeatures, WinModel, fit_win_model
from nbastats.analysis.ratings import RatingRow, fit_ratings

MODEL_VERSION = "ridge-logit-1"

# Partidos previos que necesita cada equipo para que su rating signifique algo.
# Es el mismo umbral con el que se midió la línea base del récord (64,4 %): si
# se compara contra ella, hay que evaluar el mismo conjunto o la comparación
# está trucada.
MIN_PREVIOS = 20

# Filas mínimas para que la regresión de ratings tenga sentido: con 30 equipos
# hay 62 parámetros, y por debajo de ~120 filas el ajuste es casi todo prior.
MIN_FILAS_RATING = 120


@dataclass(frozen=True)
class GameRow:
    """Un partido con lo que se sabía antes de jugarlo."""

    game_id: str
    season_id: str
    date: dt.date
    home_id: int
    away_id: int
    home_won: bool
    margin: float
    home_pts_per_100: float | None
    away_pts_per_100: float | None
    home_rest: float
    away_rest: float
    home_b2b: bool
    away_b2b: bool


@dataclass(frozen=True)
class Prediction:
    game_id: str
    season_id: str
    features: GameFeatures
    margin: float
    home_won: bool
    prob: float
    prob_logit: float
    prob_margin: float
    expected_margin: float
    sigma: float
    train_games: int


def _features(g: GameRow, neto_local: float, neto_visitante: float) -> GameFeatures:
    # El descanso se acota en 4 días: entre 4 y 12 no hay diferencia práctica y
    # sin acotar los parones de temporada dominarían el coeficiente.
    return GameFeatures(
        rating_diff=neto_local - neto_visitante,
        is_home_court=True,
        rest_diff=min(g.home_rest, 4.0) - min(g.away_rest, 4.0),
        b2b_diff=(1.0 if g.away_b2b else 0.0) - (1.0 if g.home_b2b else 0.0),
    )


def walk_forward(games: Sequence[GameRow]) -> tuple[list[Prediction], dict]:
    """Genera las variables de cada partido con ratings sin fuga temporal.

    Devuelve `(muestras, ratings_finales_por_temporada)`.
    """
    por_temporada: dict[str, list[GameRow]] = defaultdict(list)
    for g in games:
        por_temporada[g.season_id].append(g)

    muestras: list[Prediction] = []
    finales: dict[str, object] = {}

    for season in sorted(por_temporada):
        del_dia: dict[dt.date, list[GameRow]] = defaultdict(list)
        for g in por_temporada[season]:
            del_dia[g.date].append(g)

        historial: list[RatingRow] = []
        jugados: dict[int, int] = defaultdict(int)
        modelo = None

        for fecha in sorted(del_dia):
            # 1) Ajustar con lo ANTERIOR. Los partidos de hoy aún no están.
            if len(historial) >= MIN_FILAS_RATING:
                modelo = fit_ratings(historial)

            # 2) Predecir los de hoy.
            for g in del_dia[fecha]:
                if not modelo:
                    continue
                if jugados[g.home_id] < MIN_PREVIOS or jugados[g.away_id] < MIN_PREVIOS:
                    continue
                local = modelo.ratings.get(g.home_id)
                visitante = modelo.ratings.get(g.away_id)
                if not local or not visitante:
                    continue
                muestras.append(
                    Prediction(
                        game_id=g.game_id, season_id=season,
                        features=_features(g, local.net, visitante.net),
                        margin=g.margin, home_won=g.home_won,
                        prob=0.0, prob_logit=0.0, prob_margin=0.0,
                        expected_margin=0.0, sigma=0.0, train_games=0,
                    )
                )

            # 3) Y solo ahora entran al historial.
            for g in del_dia[fecha]:
                for tid, oid, casa, p100 in (
                    (g.home_id, g.away_id, True, g.home_pts_per_100),
                    (g.away_id, g.home_id, False, g.away_pts_per_100),
                ):
                    if p100 is not None:
                        historial.append(RatingRow(tid, oid, casa, p100))
                        jugados[tid] += 1

        if modelo:
            finales[season] = fit_ratings(historial) or modelo

    return muestras, finales


def evaluate(
    muestras: Sequence[Prediction],
) -> tuple[list[Prediction], dict[str, WinModel]]:
    """Rellena las probabilidades entrenando solo con temporadas anteriores.

    Devuelve también los MODELOS, uno por temporada evaluada, para que puedan
    persistirse. Antes se descartaban al terminar, y el endpoint del simulador
    acabó reimplementando la fórmula con constantes escritas a mano porque no
    tenía de dónde leer los coeficientes.

    La primera temporada se descarta entera: no hay nada anterior con lo que
    entrenar, y usar la propia sería exactamente la fuga que este módulo existe
    para evitar.
    """
    temporadas = sorted({m.season_id for m in muestras})
    salida: list[Prediction] = []
    modelos: dict[str, WinModel] = {}

    for i, season in enumerate(temporadas):
        if i == 0:
            continue
        entren = [m for m in muestras if m.season_id in temporadas[:i]]
        modelo: WinModel | None = fit_win_model(
            [m.features for m in entren],
            [m.margin for m in entren],
            [m.home_won for m in entren],
        )
        if not modelo:
            continue
        modelos[season] = modelo
        for m in (x for x in muestras if x.season_id == season):
            salida.append(
                Prediction(
                    game_id=m.game_id, season_id=m.season_id, features=m.features,
                    margin=m.margin, home_won=m.home_won,
                    prob=modelo.probability(m.features),
                    prob_logit=modelo.probability_logit(m.features),
                    prob_margin=modelo.probability_margin(m.features),
                    expected_margin=modelo.expected_margin(m.features),
                    sigma=modelo.sigma,
                    train_games=modelo.n_train,
                )
            )
    return salida, modelos
