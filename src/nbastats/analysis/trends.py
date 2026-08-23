"""Detección de tendencias: jugadores en declive y al alza.

Tres decisiones metodológicas que condicionan los resultados:

1. **La regresión corre sobre los valores CRUDOS, nunca sobre la media móvil.**
   Suavizar una serie y luego regresarla es un error clásico: los puntos
   consecutivos de una media móvil comparten observaciones, así que están
   autocorrelacionados, y eso reduce artificialmente el p-valor. Una serie de
   puro ruido puede salir "significativamente decreciente" solo por haberla
   suavizado antes. La media móvil aquí es exclusivamente para dibujar.

2. **Se exigen dos tests de acuerdo** (Mann-Kendall y que el IC de la pendiente
   excluya el cero) antes de declarar una tendencia. Mann-Kendall es no
   paramétrico y aguanta los outliers que abundan en una serie de partidos; la
   regresión aporta el tamaño del efecto. Que ambos coincidan reduce mucho los
   falsos positivos.

3. **Se trabaja sobre tasas** (per-36, per-100), no sobre totales por partido.
   Ver `rates.py`.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pymannkendall as mk
import ruptures as rpt
from scipy import stats

from nbastats.analysis.reliability import Reliability, reliability_for

# Partidos mínimos para intentar siquiera una tendencia. Por debajo de esto el
# resultado es ruido con forma de recta.
MIN_GAMES_FOR_TREND = 20

# Longitud mínima de un tramo entre dos puntos de cambio. Evita que una mala
# racha de tres partidos se reporte como "cambio de nivel".
MIN_SEGMENT_GAMES = 10

# Edad del pico de rendimiento en la NBA, según la literatura. Solo se usa como
# valor por defecto: en cuanto haya datos cargados conviene reajustar la curva
# con `fit_age_curve` sobre la liga entera.
DEFAULT_PEAK_AGE = 26.5

GAMES_PER_SEASON = 82


class TrendDirection(enum.StrEnum):
    ALZA = "alza"
    DECLIVE = "declive"
    ESTABLE = "estable"
    INDETERMINADA = "indeterminada"


@dataclass(frozen=True)
class TrendResult:
    n: int
    direction: TrendDirection
    reliability: Reliability

    slope_per_game: float
    slope_ci95: tuple[float, float]
    slope_per_season: float
    """Pendiente escalada a 82 partidos: la unidad en la que se piensa."""

    intercept: float
    r_squared: float
    p_value: float

    mk_trend: str
    mk_p_value: float
    tau: float
    """Tau de Kendall: fuerza de la tendencia, entre -1 y 1."""

    change_points: list[int] = field(default_factory=list)
    """Índices donde el nivel de la serie cambia de forma sostenida."""

    note: str = ""

    @property
    def is_significant(self) -> bool:
        return self.direction in (TrendDirection.ALZA, TrendDirection.DECLIVE)


def rolling_mean(values: Sequence[float], window: int = 25) -> list[float | None]:
    """Media móvil, SOLO para dibujar.

    Devuelve None en las primeras `window - 1` posiciones en lugar de rellenar
    con medias parciales: un punto calculado con 3 partidos y otro con 25 no son
    comparables, y pintarlos juntos sugiere una estabilidad que no existe.
    """
    if window < 1:
        raise ValueError("window debe ser >= 1")

    arr = np.asarray(values, dtype=float)
    if arr.size < window:
        return [None] * arr.size

    kernel = np.ones(window) / window
    smoothed = np.convolve(arr, kernel, mode="valid")
    return [None] * (window - 1) + smoothed.tolist()


def detect_change_points(
    values: Sequence[float],
    *,
    min_segment: int = MIN_SEGMENT_GAMES,
    penalty_scale: float = 3.0,
) -> list[int]:
    """Localiza cambios sostenidos de nivel (algoritmo PELT).

    Responde a "¿CUÁNDO cambió?", que suele importar más que "¿cambió?": una
    lesión, un traspaso o un cambio de rol producen un escalón, no una pendiente
    suave. Una regresión lineal sobre un escalón devuelve una pendiente que no
    describe nada real.

    La penalización se escala con la varianza de la serie para que el mismo
    parámetro sirva para puntos (varianza alta) y para porcentajes (baja).
    """
    arr = np.asarray(values, dtype=float)
    if arr.size < 2 * min_segment:
        return []

    variance = float(arr.var())
    if variance == 0:
        return []

    penalty = penalty_scale * variance * math.log(arr.size)

    try:
        algo = rpt.Pelt(model="l2", min_size=min_segment, jump=1).fit(
            arr.reshape(-1, 1)
        )
        breaks = algo.predict(pen=penalty)
    except Exception:
        # ruptures puede fallar con series degeneradas; no tener puntos de
        # cambio es una respuesta válida, no un error del análisis.
        return []

    # PELT incluye siempre el final de la serie como último "corte".
    return [b for b in breaks if 0 < b < arr.size]


def analyze_trend(
    values: Sequence[float],
    *,
    min_games: int = MIN_GAMES_FOR_TREND,
    alpha: float = 0.05,
    find_change_points: bool = True,
) -> TrendResult:
    """Analiza la trayectoria de un jugador en una estadística.

    Args:
        values: la serie en orden cronológico. Deben ser TASAS (per-36,
            per-100, TS%...), no totales por partido.
        min_games: por debajo de esto no se intenta nada.
        alpha: nivel de significación para ambos tests.
        find_change_points: detectar escalones además de la pendiente.
    """
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    arr = arr[np.isfinite(arr)]
    n = int(arr.size)
    reliability = reliability_for(n)

    if n < min_games:
        return _indeterminate(
            n,
            reliability,
            f"Solo {n} partidos con dato; hacen falta {min_games} para estimar "
            f"una tendencia.",
        )

    x = np.arange(n, dtype=float)

    # --- Regresión: tamaño del efecto ---
    reg = stats.linregress(x, arr)
    slope = float(reg.slope)
    stderr = float(reg.stderr)

    if not math.isfinite(stderr) or stderr == 0:
        return _indeterminate(n, reliability, "La serie no tiene variación suficiente.")

    t_crit = float(stats.t.ppf(1 - alpha / 2, df=n - 2))
    ci = (slope - t_crit * stderr, slope + t_crit * stderr)

    # --- Mann-Kendall: robusto a outliers ---
    try:
        mk_result = mk.original_test(arr, alpha=alpha)
        mk_trend, mk_p, tau = str(mk_result.trend), float(mk_result.p), float(mk_result.Tau)
    except Exception:
        mk_trend, mk_p, tau = "no trend", 1.0, 0.0

    # --- Veredicto: los dos tests tienen que coincidir ---
    ci_excludes_zero = ci[0] > 0 or ci[1] < 0
    mk_significant = mk_p < alpha and mk_trend != "no trend"

    if ci_excludes_zero and mk_significant:
        direction = (
            TrendDirection.ALZA if slope > 0 else TrendDirection.DECLIVE
        )
    else:
        direction = TrendDirection.ESTABLE

    change_points = (
        detect_change_points(arr) if find_change_points else []
    )

    return TrendResult(
        n=n,
        direction=direction,
        reliability=reliability,
        slope_per_game=slope,
        slope_ci95=ci,
        slope_per_season=slope * GAMES_PER_SEASON,
        intercept=float(reg.intercept),
        r_squared=float(reg.rvalue) ** 2,
        p_value=float(reg.pvalue),
        mk_trend=mk_trend,
        mk_p_value=mk_p,
        tau=tau,
        change_points=change_points,
        note=_trend_note(n, direction, slope, ci, change_points, reliability),
    )


def _indeterminate(n: int, reliability: Reliability, note: str) -> TrendResult:
    nan = float("nan")
    return TrendResult(
        n=n,
        direction=TrendDirection.INDETERMINADA,
        reliability=reliability,
        slope_per_game=nan,
        slope_ci95=(nan, nan),
        slope_per_season=nan,
        intercept=nan,
        r_squared=nan,
        p_value=1.0,
        mk_trend="no trend",
        mk_p_value=1.0,
        tau=0.0,
        change_points=[],
        note=note,
    )


def _trend_note(
    n: int,
    direction: TrendDirection,
    slope: float,
    ci: tuple[float, float],
    change_points: list[int],
    reliability: Reliability,
) -> str:
    per_season = slope * GAMES_PER_SEASON

    if direction is TrendDirection.ESTABLE:
        margen = (ci[1] - ci[0]) / 2 * GAMES_PER_SEASON
        base = (
            f"{n} partidos. Sin tendencia detectable: el cambio por temporada "
            f"cabe dentro de ±{margen:.2f}, que incluye el cero."
        )
    else:
        palabra = "sube" if direction is TrendDirection.ALZA else "baja"
        base = (
            f"{n} partidos. La serie {palabra} {abs(per_season):.2f} por cada 82 "
            f"partidos (IC95 {ci[0] * GAMES_PER_SEASON:+.2f} a "
            f"{ci[1] * GAMES_PER_SEASON:+.2f}), y los dos tests coinciden."
        )

    if change_points:
        base += (
            f" Ojo: hay {len(change_points)} cambio(s) de nivel "
            f"(partido{'s' if len(change_points) > 1 else ''} "
            f"{', '.join(str(c) for c in change_points)}); una sola recta "
            f"describe mal esta trayectoria."
        )

    if reliability in (Reliability.BAJA, Reliability.INSUFICIENTE):
        base += " Muestra pequeña: tomar como indicio, no como conclusión."

    return base


# =========================================================================
# Curvas de edad
# =========================================================================


@dataclass(frozen=True)
class AgeCurve:
    """Curva cuadrática de rendimiento contra edad, ajustada sobre la liga."""

    a: float
    b: float
    c: float
    peak_age: float
    n_observations: int

    def expected(self, age: float) -> float:
        return self.a * age**2 + self.b * age + self.c

    def relative_to_peak(self, age: float) -> float:
        """Rendimiento esperado a esa edad como fracción del pico."""
        peak_value = self.expected(self.peak_age)
        return self.expected(age) / peak_value if peak_value else float("nan")


def fit_age_curve(ages: Sequence[float], values: Sequence[float]) -> AgeCurve | None:
    """Ajusta una curva de edad transversal a partir de datos de liga.

    Se ajusta con datos propios en lugar de usar una constante de la literatura
    porque la forma depende de la estadística: los tiradores envejecen mucho
    mejor que los que viven de la explosividad, y el pico de asistencias llega
    más tarde que el de rebotes.

    ⚠️ SESGO DE SUPERVIVENCIA — LEER ANTES DE USAR ESTO PARA DECIDIR NADA.

    Un ajuste transversal (todos los jugadores, todas las edades, a la vez)
    **subestima el declive por edad**, y bastante. El motivo: solo entran en la
    muestra los jugadores que siguen siendo lo bastante buenos como para jugar.
    Quien declina de verdad no aparece con 36 años promediando poco — aparece
    fuera de la NBA, y desaparece del cálculo. Lo que queda a los 38 son los
    supervivientes, que por definición son los que peor envejecieron.

    Se ve en los datos de este proyecto: ajustado sobre 1.561 temporadas de
    jugadores con 30+ partidos y 15+ minutos, la curva sale con el pico en
    **29,0 años** y solo un 9% de caída a los 39 — cifras que ninguna literatura
    de envejecimiento deportivo respalda.

    La corrección estándar es el **método delta**: comparar a cada jugador
    consigo mismo entre temporadas consecutivas y promediar esos cambios por
    edad. Al ser intra-jugador, no lo afecta quién entra o sale de la liga.
    No está implementado todavía; hasta que lo esté, esta función sirve para
    explorar la forma de la curva, NO para afirmar cuánto declive es "normal"
    a una edad dada.
    """
    x = np.asarray(ages, dtype=float)
    y = np.asarray(values, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]

    if x.size < 30 or np.unique(x).size < 5:
        return None

    a, b, c = np.polyfit(x, y, 2)
    if a >= 0:
        # Parábola hacia arriba: no describe una curva de rendimiento (implicaría
        # que se mejora indefinidamente con la edad). Casi siempre significa que
        # el rango de edades es demasiado estrecho.
        return None

    return AgeCurve(
        a=float(a),
        b=float(b),
        c=float(c),
        peak_age=float(-b / (2 * a)),
        n_observations=int(x.size),
    )


def age_adjusted_residuals(
    ages: Sequence[float], values: Sequence[float], curve: AgeCurve
) -> list[float]:
    """Cuánto se separa el jugador de lo esperado para su edad.

    Un residuo que cae de forma sostenida es declive de verdad. Una serie que
    baja pero sigue la curva es, simplemente, un jugador cumpliendo años.
    """
    return [
        float(v - curve.expected(a)) if v is not None else float("nan")
        for a, v in zip(ages, values, strict=True)
    ]
