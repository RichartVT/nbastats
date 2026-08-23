"""Estimación honesta de splits condicionales.

El problema que resuelve este módulo:

Preguntar "¿cuántos puntos anota este jugador en sábado?" es fácil en SQL y
peligroso en estadística. Un jugador tiene ~12 sábados por temporada. Con una
desviación típica de ~6 puntos, el error estándar de esa media es ~1.7 puntos:
una diferencia de 3 puntos frente a su promedio general es indistinguible de
cero. Y como hay 7 días × ~500 jugadores × ~10 estadísticas ≈ 35.000
comparaciones posibles, con α=0.05 aparecerían ~1.750 "patrones significativos"
producidos exclusivamente por el azar.

La respuesta de este módulo no es prohibir la consulta, sino devolverla
acompañada de lo que hace falta para interpretarla: tamaño de muestra,
intervalo de confianza, media encogida hacia el promedio del jugador, y un
valor q corregido por comparaciones múltiples.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats

# Umbrales de tamaño de muestra. Se exportan para que la API y el frontend
# usen exactamente los mismos, en lugar de duplicar constantes.
N_ALTA = 40
N_MEDIA = 15


class Reliability(enum.StrEnum):
    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"
    INSUFICIENTE = "insuficiente"


def reliability_for(n: int) -> Reliability:
    if n < 2:
        return Reliability.INSUFICIENTE
    if n >= N_ALTA:
        return Reliability.ALTA
    if n >= N_MEDIA:
        return Reliability.MEDIA
    return Reliability.BAJA


@dataclass(frozen=True)
class SplitEstimate:
    """Resultado de un split, con todo lo necesario para no malinterpretarlo."""

    label: str
    n: int
    raw_mean: float
    """Media cruda del split. Es el número que pediría una consulta SQL ingenua."""

    shrunk_mean: float
    """Media encogida hacia el promedio general del jugador.

    Con pocos partidos queda casi pegada al promedio general, que es la
    estimación honesta cuando no hay evidencia de que el split sea distinto.
    """

    std_dev: float
    std_error: float
    ci95_low: float
    ci95_high: float

    baseline: float
    """Promedio del jugador fuera de este split, para comparar."""

    diff_vs_baseline: float
    p_value: float
    q_value: float
    """p corregido por comparaciones múltiples (Benjamini-Hochberg, FDR)."""

    reliability: Reliability
    distinguishable: bool
    """True solo si el split se separa del resto tras corregir por FDR."""

    note: str

    @property
    def display_mean(self) -> float:
        """Lo que debería enseñar la UI por defecto.

        Si el split no es distinguible del resto, la media encogida comunica
        mejor la realidad que la cruda.
        """
        return self.raw_mean if self.distinguishable else self.shrunk_mean


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """Valores q por FDR (Benjamini-Hochberg).

    Sin esto, escanear muchos jugadores × splits garantiza falsos hallazgos:
    con 35.000 comparaciones y α=0,05 salen ~1.750 "patrones" por puro azar.
    """
    m = len(p_values)
    if m == 0:
        return []

    order = np.argsort(p_values)
    ordered = np.asarray(p_values, dtype=float)[order]

    # q_(i) = min_{j >= i} ( m/j * p_(j) ), acumulado desde el final.
    ranks = np.arange(1, m + 1)
    scaled = ordered * m / ranks
    q_ordered = np.minimum.accumulate(scaled[::-1])[::-1]
    q_ordered = np.clip(q_ordered, 0.0, 1.0)

    q = np.empty(m, dtype=float)
    q[order] = q_ordered
    return q.tolist()


def _estimate_tau_squared(
    means: np.ndarray, ns: np.ndarray, within_var: float
) -> float:
    """Varianza real entre splits, por el método de los momentos.

    La dispersión observada entre las medias de los splits mezcla dos cosas:
    diferencias auténticas y ruido de muestreo. Se resta la parte de ruido
    esperada; si no queda nada, tau² = 0 y el encogimiento es total — que es la
    conclusión correcta cuando los splits no se distinguen entre sí.
    """
    if len(means) < 2:
        return 0.0

    observed_var = float(np.var(means, ddof=1))
    expected_noise = float(np.mean(within_var / np.maximum(ns, 1)))
    return max(0.0, observed_var - expected_noise)


def analyze_splits(
    groups: Mapping[str, Sequence[float]],
    *,
    alpha: float = 0.05,
) -> dict[str, SplitEstimate]:
    """Analiza a la vez todos los niveles de una dimensión de split.

    Se procesan juntos y no de uno en uno por dos motivos estadísticos:

    1. El encogimiento bayesiano empírico necesita ver la dispersión ENTRE
       splits para saber cuánto encoger cada uno.
    2. La corrección por comparaciones múltiples solo tiene sentido sobre el
       conjunto de comparaciones que realmente se hicieron.

    Args:
        groups: nivel -> valores observados. Por ejemplo
            {"sábado": [12, 8, 20, ...], "lunes": [...], ...}
        alpha: tasa de falso descubrimiento admitida.

    Returns:
        Un SplitEstimate por nivel, en el mismo orden de entrada.
    """
    labels = list(groups.keys())
    samples = {k: np.asarray(v, dtype=float) for k, v in groups.items()}
    all_values = np.concatenate([v for v in samples.values() if v.size]) if any(
        v.size for v in samples.values()
    ) else np.array([])

    if all_values.size == 0:
        return {
            label: _empty_estimate(label) for label in labels
        }

    grand_mean = float(all_values.mean())
    # Varianza intra-jugador: cuánto varía la estadística de partido a partido.
    within_var = float(all_values.var(ddof=1)) if all_values.size > 1 else 0.0

    populated = [label for label in labels if samples[label].size >= 1]
    means = np.array([samples[label].mean() for label in populated])
    ns = np.array([samples[label].size for label in populated], dtype=float)
    tau_sq = _estimate_tau_squared(means, ns, within_var)

    # Primera pasada: estadísticos por grupo y p-valor contra el resto.
    raw: dict[str, dict] = {}
    p_values: list[float] = []
    for label in labels:
        values = samples[label]
        n = int(values.size)
        others = np.concatenate(
            [samples[o] for o in labels if o != label and samples[o].size]
        ) if any(samples[o].size for o in labels if o != label) else np.array([])

        baseline = float(others.mean()) if others.size else grand_mean

        if n == 0:
            raw[label] = None
            p_values.append(1.0)
            continue

        mean = float(values.mean())
        sd = float(values.std(ddof=1)) if n > 1 else 0.0
        se = sd / math.sqrt(n) if n > 1 else float("inf")

        if n > 1 and se > 0 and math.isfinite(se):
            t_crit = float(stats.t.ppf(1 - alpha / 2, df=n - 1))
            ci_low, ci_high = mean - t_crit * se, mean + t_crit * se
        else:
            ci_low, ci_high = float("-inf"), float("inf")

        # Welch contra el complemento (no contra el total, que incluiría al
        # propio grupo y correlacionaría las dos muestras).
        if n > 1 and others.size > 1:
            p = float(stats.ttest_ind(values, others, equal_var=False).pvalue)
            if not math.isfinite(p):
                p = 1.0
        else:
            p = 1.0

        # Encogimiento: peso = señal / (señal + ruido).
        noise = within_var / n if n else float("inf")
        weight = tau_sq / (tau_sq + noise) if (tau_sq + noise) > 0 else 0.0
        shrunk = weight * mean + (1 - weight) * baseline

        raw[label] = {
            "n": n,
            "mean": mean,
            "sd": sd,
            "se": se,
            "ci": (ci_low, ci_high),
            "baseline": baseline,
            "shrunk": shrunk,
            "p": p,
        }
        p_values.append(p)

    q_values = benjamini_hochberg(p_values)

    result: dict[str, SplitEstimate] = {}
    for label, q in zip(labels, q_values, strict=True):
        info = raw[label]
        if info is None:
            result[label] = _empty_estimate(label)
            continue

        rel = reliability_for(info["n"])
        distinguishable = bool(q < alpha and rel is not Reliability.INSUFICIENTE)

        result[label] = SplitEstimate(
            label=label,
            n=info["n"],
            raw_mean=info["mean"],
            shrunk_mean=info["shrunk"],
            std_dev=info["sd"],
            std_error=info["se"],
            ci95_low=info["ci"][0],
            ci95_high=info["ci"][1],
            baseline=info["baseline"],
            diff_vs_baseline=info["mean"] - info["baseline"],
            p_value=info["p"],
            q_value=q,
            reliability=rel,
            distinguishable=distinguishable,
            note=_build_note(label, info, rel, distinguishable),
        )
    return result


def _empty_estimate(label: str) -> SplitEstimate:
    nan = float("nan")
    return SplitEstimate(
        label=label,
        n=0,
        raw_mean=nan,
        shrunk_mean=nan,
        std_dev=nan,
        std_error=nan,
        ci95_low=nan,
        ci95_high=nan,
        baseline=nan,
        diff_vs_baseline=nan,
        p_value=1.0,
        q_value=1.0,
        reliability=Reliability.INSUFICIENTE,
        distinguishable=False,
        note="Sin partidos en este split.",
    )


def _build_note(
    label: str, info: dict, rel: Reliability, distinguishable: bool
) -> str:
    """Explicación en lenguaje llano — es lo que se enseña junto al número."""
    n = info["n"]

    if rel is Reliability.INSUFICIENTE:
        return f"Solo {n} partido(s) en '{label}': no se puede estimar nada."

    if distinguishable:
        direction = "por encima" if info["mean"] > info["baseline"] else "por debajo"
        return (
            f"{n} partidos. Diferencia de {abs(info['mean'] - info['baseline']):.1f} "
            f"{direction} del resto, y se sostiene tras corregir por comparaciones "
            f"múltiples."
        )

    margin = info["ci"][1] - info["mean"]
    if math.isfinite(margin):
        return (
            f"{n} partidos, margen de error ±{margin:.1f}. La diferencia con el "
            f"resto no se distingue del ruido: se muestra la media encogida hacia "
            f"su promedio general."
        )
    return f"{n} partidos: muestra demasiado pequeña para un intervalo de confianza."
