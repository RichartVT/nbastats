"""De una diferencia de rating a una probabilidad de victoria.

DOS CAMINOS QUE TIENEN QUE ESTAR DE ACUERDO. Es la regla de la casa, la misma
que `analyze_trend` aplica exigiendo Mann-Kendall **y** un intervalo que excluya
el cero antes de declarar una tendencia:

1. Una **regresión logística** sobre el resultado (ganó / perdió).
2. Una **regresión lineal sobre el margen**, que da μ y σ, y de ahí
   `P = Φ(μ/σ)`.

Son dos rutas independientes: la primera solo ve el signo, la segunda ve la
magnitud y asume normalidad. Si coinciden dentro de un par de puntos, la
probabilidad es creíble. Si discrepan, hay un problema y el modelo lo dice en
vez de elegir la que más guste.

POCAS VARIABLES, Y A PROPÓSITO. Diferencia de rating, localía, descanso y
back-to-back. Con ~4.500 partidos de entrenamiento y un ruido de σ≈13 puntos por
partido, cada variable extra compra una milésima de log-loss y vende
sobreajuste. La señal disponible cabe en cinco coeficientes.

REGLA DE BOLSILLO ÚTIL. Cerca del 50 %, `dP/dmargen = φ(0)/σ ≈ 0,031`: **cada
punto de margen esperado vale unos 3 puntos porcentuales de probabilidad.** Con
eso se puede auditar a ojo cualquier salida del modelo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats

# Nombres de las variables, en orden. La constante va aparte.
FEATURES = ("rating_diff", "home", "rest_diff", "b2b_diff")


@dataclass(frozen=True)
class GameFeatures:
    """Lo que se sabe ANTES del salto inicial. Todo desde el lado del local."""

    rating_diff: float
    """Neto del local menos neto del visitante, por 100 posesiones. SIN localía:
    la localía es una variable aparte para poder medirla."""

    is_home_court: bool = True
    """False en sede neutral, donde no hay público propio ni ausencia de viaje."""

    rest_diff: float = 0.0
    """Días de descanso del local menos los del visitante, acotados."""

    b2b_diff: float = 0.0
    """+1 si solo el visitante juega su segundo partido en dos días, −1 si solo
    el local, 0 si ambos o ninguno."""

    def vector(self) -> list[float]:
        return [
            self.rating_diff,
            1.0 if self.is_home_court else 0.0,
            self.rest_diff,
            self.b2b_diff,
        ]


@dataclass(frozen=True)
class WinModel:
    logit_params: dict[str, float]
    margin_params: dict[str, float]
    sigma: float
    """Desviación típica residual del margen. Es la que convierte puntos en
    probabilidad, y la que dice cuánta incertidumbre es irreducible."""

    n_train: int

    def expected_margin(self, f: GameFeatures) -> float:
        v = f.vector()
        return self.margin_params["const"] + sum(
            self.margin_params[n] * x for n, x in zip(FEATURES, v, strict=True)
        )

    def probability_logit(self, f: GameFeatures) -> float:
        v = f.vector()
        z = self.logit_params["const"] + sum(
            self.logit_params[n] * x for n, x in zip(FEATURES, v, strict=True)
        )
        return float(1.0 / (1.0 + np.exp(-z)))

    def probability_margin(self, f: GameFeatures) -> float:
        """`Φ(μ/σ)`: la vía que pasa por la magnitud del margen."""
        if self.sigma <= 0:
            return 0.5
        return float(stats.norm.cdf(self.expected_margin(f) / self.sigma))

    def probability(self, f: GameFeatures) -> float:
        """La media de las dos rutas.

        Promediarlas y no elegir una es deliberado: si están de acuerdo da
        igual cuál se use, y si discrepan la media es menos mala que apostar
        por la que más guste. `agrees()` dice cuándo hay que desconfiar.
        """
        return (self.probability_logit(f) + self.probability_margin(f)) / 2

    def agrees(self, f: GameFeatures, *, tol: float = 0.03) -> bool:
        """¿Coinciden las dos rutas dentro de `tol`?"""
        return abs(self.probability_logit(f) - self.probability_margin(f)) <= tol

    @property
    def points_per_percent(self) -> float:
        """Cuántos puntos de margen vale un punto porcentual, cerca del 50 %."""
        return self.sigma / float(stats.norm.pdf(0)) / 100


def fit_win_model(
    features: Sequence[GameFeatures],
    margins: Sequence[float],
    outcomes: Sequence[bool],
) -> WinModel | None:
    """Ajusta las dos rutas sobre los mismos datos.

    Devuelve `None` si no hay muestra suficiente o si el resultado no varía:
    con todos los partidos ganados por el local no hay nada que aprender, y un
    modelo ajustado sobre eso daría 1,0 para todo.
    """
    import statsmodels.api as sm

    if len(features) < 100:
        return None
    y = np.asarray(outcomes, dtype=float)
    if len(np.unique(y)) < 2:
        return None

    X = np.array([f.vector() for f in features], dtype=float)
    # Se descartan columnas constantes: en un backtest sin sedes neutrales,
    # `home` vale 1 en todas las filas y colisiona con la constante.
    utiles = [i for i in range(X.shape[1]) if np.ptp(X[:, i]) > 0]
    Xu = sm.add_constant(X[:, utiles], has_constant="add")

    try:
        logit = sm.Logit(y, Xu).fit(disp=False)
        ols = sm.OLS(np.asarray(margins, dtype=float), Xu).fit()
    except Exception:  # noqa: BLE001 — separación perfecta o matriz singular
        return None

    def desempaqueta(ajuste) -> dict[str, float]:
        salida = {"const": float(ajuste.params[0])}
        salida.update(dict.fromkeys(FEATURES, 0.0))
        for pos, col in enumerate(utiles, start=1):
            salida[FEATURES[col]] = float(ajuste.params[pos])
        return salida

    residuos = np.asarray(margins, dtype=float) - ols.fittedvalues
    return WinModel(
        logit_params=desempaqueta(logit),
        margin_params=desempaqueta(ols),
        sigma=float(np.std(residuos, ddof=len(utiles) + 1)),
        n_train=len(features),
    )


def model_from_params(
    logit_params: dict, margin_params: dict, sigma: float, n_train: int = 0
) -> WinModel:
    """Reconstruye un `WinModel` a partir de sus coeficientes guardados.

    Es lo que garantiza que el simulador y el informe de validación usen el
    MISMO modelo. La alternativa —reimplementar la fórmula donde se necesite—
    ya se probó y produjo una pantalla que calculaba otra cosa sin avisar.

    Se rellenan con 0.0 las variables ausentes: un coeficiente que falta es una
    variable que no entró en el ajuste, y su efecto es exactamente ninguno.
    """
    def completo(p: dict) -> dict[str, float]:
        salida = {"const": float(p.get("const", 0.0))}
        salida.update({n: float(p.get(n, 0.0)) for n in FEATURES})
        return salida

    return WinModel(
        logit_params=completo(logit_params),
        margin_params=completo(margin_params),
        sigma=float(sigma),
        n_train=n_train,
    )
