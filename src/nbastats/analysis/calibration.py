"""Si el modelo dice 70 %, ¿gana el 70 % de las veces?

La precisión sola no detecta un modelo roto. Uno que acierta el 65 % pero dice
"80 %" cuando en realidad gana el 60 % tiene la misma precisión que uno bien
calibrado y es mucho peor: sus números no significan lo que dicen. Por eso aquí
no se publica una probabilidad sin su calibración al lado.

EL AVISO QUE VA ANTES DE LA TABLA, NO DESPUÉS. Con 4.596 partidos repartidos en
diez tramos, cada tramo tiene ~460 y su error típico es √(0,25/460) ≈ 0,023, o
sea **±4,6 puntos porcentuales**. Con esta muestra no se puede detectar un
desajuste menor de ~4 pp. Decirlo primero es lo que impide leer la ondulación de
la curva como si fuera información.

Y por lo mismo, el ECE esperado bajo calibración PERFECTA no es cero: es del
orden de 0,019 con estos tamaños. Un ECE de 0,022 no es un defecto, es el suelo
de ruido. `ece_noise_floor` lo calcula para poder enseñarlos juntos.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# Se recorta la probabilidad antes del logaritmo: un 0 o un 1 exactos dan
# log-loss infinita y un solo partido arruinaría la métrica de todos.
_EPS = 1e-15


@dataclass(frozen=True)
class CalibrationBin:
    """Un tramo del diagrama de fiabilidad."""

    low: float
    high: float
    n: int
    mean_predicted: float
    observed: float
    ci95_low: float
    ci95_high: float

    @property
    def calibrated(self) -> bool:
        """¿La frecuencia real cae dentro de lo que el modelo prometió?

        Se compara el intervalo de la frecuencia OBSERVADA contra la
        probabilidad media predicha. Si el intervalo la contiene, este tramo no
        contradice al modelo — que no es lo mismo que confirmarlo.
        """
        return self.ci95_low <= self.mean_predicted <= self.ci95_high


@dataclass(frozen=True)
class CalibrationReport:
    bins: list[CalibrationBin]
    ece: float
    ece_floor: float
    slope: float | None
    intercept: float | None
    note: str

    @property
    def within_noise(self) -> bool:
        """El desajuste no supera lo que la propia muestra puede detectar."""
        return self.ece <= self.ece_floor


def _as_arrays(p: Sequence[float], y: Sequence[bool | int]) -> tuple[np.ndarray, np.ndarray]:
    pa = np.asarray(p, dtype=float)
    ya = np.asarray(y, dtype=float)
    if pa.shape != ya.shape:
        raise ValueError("Probabilidades y resultados deben tener el mismo tamaño.")
    return pa, ya


def brier(p: Sequence[float], y: Sequence[bool | int]) -> float:
    """Error cuadrático medio de la probabilidad. Más bajo, mejor.

    A diferencia de la precisión, castiga la confianza mal puesta: decir 0,95 y
    fallar duele mucho más que decir 0,55 y fallar.
    """
    pa, ya = _as_arrays(p, y)
    return float(np.mean((pa - ya) ** 2))


def log_loss(p: Sequence[float], y: Sequence[bool | int]) -> float:
    """Verosimilitud negativa media, en logaritmo natural."""
    pa, ya = _as_arrays(p, y)
    pa = np.clip(pa, _EPS, 1 - _EPS)
    return float(-np.mean(ya * np.log(pa) + (1 - ya) * np.log(1 - pa)))


def brier_skill_score(
    p: Sequence[float], y: Sequence[bool | int], baseline: float
) -> float:
    """Cuánto mejora el Brier respecto a predecir siempre `baseline`.

    0 = no aporta nada sobre la línea base. 1 = perfecto. Negativo = peor que
    no hacer nada, que es un resultado perfectamente posible y hay que poder
    publicarlo.
    """
    _, ya = _as_arrays(p, y)
    base = float(np.mean((baseline - ya) ** 2))
    if base == 0:
        return 0.0
    return 1.0 - brier(p, y) / base


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción.

    Se usa Wilson y no el intervalo normal porque con proporciones cerca de 0 o
    de 1 —justo donde caen los tramos extremos del diagrama— el normal se sale
    del [0,1] y produce intervalos imposibles.

    >>> lo, hi = wilson_interval(50, 100)
    >>> round(lo, 3), round(hi, 3)
    (0.404, 0.596)
    """
    if n <= 0:
        return (0.0, 1.0)
    fase = successes / n
    denom = 1 + z**2 / n
    centro = (fase + z**2 / (2 * n)) / denom
    margen = z * math.sqrt(fase * (1 - fase) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def ece_noise_floor(n_per_bin: float, p: float = 0.5) -> float:
    """ECE que cabe esperar aunque la calibración sea PERFECTA.

    Con tramos finitos, la frecuencia observada se desvía de la predicha por
    puro muestreo. La desviación media absoluta de una binomial es
    `sd·√(2/π)`, y ese es el suelo. Publicar un ECE sin él invita a leer ruido
    como sesgo.
    """
    if n_per_bin <= 0:
        return 0.0
    sd = math.sqrt(p * (1 - p) / n_per_bin)
    return sd * math.sqrt(2 / math.pi)


def calibration_bins(
    p: Sequence[float], y: Sequence[bool | int], *, bins: int = 10
) -> list[CalibrationBin]:
    """Reparte las predicciones en tramos y compara promesa contra realidad.

    Los tramos son de ancho fijo y no de igual frecuencia: así el eje del
    diagrama es interpretable y los tramos vacíos se ven, que es información
    (un modelo que nunca pasa de 0,85 debe enseñarlo).
    """
    pa, ya = _as_arrays(p, y)
    bordes = np.linspace(0.0, 1.0, bins + 1)
    salida: list[CalibrationBin] = []

    for i in range(bins):
        lo, hi = float(bordes[i]), float(bordes[i + 1])
        # El último tramo incluye el 1.0; el resto son semiabiertos.
        dentro = (pa >= lo) & (pa < hi) if i < bins - 1 else (pa >= lo) & (pa <= hi)
        n = int(dentro.sum())
        if n == 0:
            continue
        aciertos = int(ya[dentro].sum())
        ci_low, ci_high = wilson_interval(aciertos, n)
        salida.append(
            CalibrationBin(
                low=lo,
                high=hi,
                n=n,
                mean_predicted=float(pa[dentro].mean()),
                observed=aciertos / n,
                ci95_low=ci_low,
                ci95_high=ci_high,
            )
        )
    return salida


def expected_calibration_error(bins: Sequence[CalibrationBin]) -> float:
    """Desajuste medio, ponderado por cuántas predicciones cayeron en cada tramo."""
    total = sum(b.n for b in bins)
    if not total:
        return 0.0
    return sum(b.n * abs(b.observed - b.mean_predicted) for b in bins) / total


def cox_calibration(
    p: Sequence[float], y: Sequence[bool | int]
) -> tuple[float | None, float | None]:
    """Pendiente e intercepto de calibración: `y ~ logit(p)`.

    Calibración perfecta es pendiente 1 e intercepto 0. Una pendiente menor que
    1 significa **exceso de confianza**: el modelo separa más de lo que debería
    y sus extremos están exagerados. Es el diagnóstico que un diagrama de diez
    tramos no da con precisión, porque cada tramo tiene demasiado poco `n`.
    """
    import statsmodels.api as sm

    pa, ya = _as_arrays(p, y)
    if len(pa) < 20 or len(np.unique(ya)) < 2:
        return (None, None)

    pa = np.clip(pa, _EPS, 1 - _EPS)
    x = np.log(pa / (1 - pa))
    X = sm.add_constant(x, has_constant="add")
    try:
        ajuste = sm.Logit(ya, X).fit(disp=False)
    except Exception:  # noqa: BLE001 — separación perfecta u otra degeneración
        return (None, None)
    return (float(ajuste.params[1]), float(ajuste.params[0]))


def calibration_report(
    p: Sequence[float], y: Sequence[bool | int], *, bins: int = 10
) -> CalibrationReport:
    """Informe completo, con el suelo de ruido incluido."""
    tramos = calibration_bins(p, y, bins=bins)
    ece = expected_calibration_error(tramos)
    n_medio = float(np.mean([b.n for b in tramos])) if tramos else 0.0
    suelo = ece_noise_floor(n_medio)
    pendiente, intercepto = cox_calibration(p, y)

    if not tramos:
        nota = "Sin predicciones que evaluar."
    elif ece <= suelo:
        nota = (
            f"El desajuste medio ({ece:.3f}) no supera el suelo de ruido de esta "
            f"muestra ({suelo:.3f}): con ~{n_medio:.0f} partidos por tramo no se "
            "puede distinguir de una calibración perfecta."
        )
    else:
        nota = (
            f"Desajuste medio de {ece:.3f}, por encima del suelo de ruido "
            f"({suelo:.3f}). Con ~{n_medio:.0f} partidos por tramo, solo son "
            "detectables desviaciones de unos 4 puntos porcentuales."
        )
    return CalibrationReport(
        bins=tramos, ece=ece, ece_floor=suelo,
        slope=pendiente, intercept=intercepto, note=nota,
    )
