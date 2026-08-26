"""Cuánto se repite cada componente del juego: habilidad, ruido, o mezcla.

Este módulo va PRIMERO y todo lo demás cuelga de él. La afirmación "el
porcentaje de triple del rival es suerte" es una opinión hasta que alguien la
mide; a partir de aquí es una cifra sacada de estos 13.204 registros.

LA IDEA, EN UNA LÍNEA. La dispersión que se observa entre equipos mezcla dos
cosas: diferencias reales de habilidad y ruido de muestreo. Separarlas da el
número que gobierna el motor entero:

    k = varianza_intra / varianza_verdadera_entre_equipos

`k` está EN PARTIDOS y se lee directo: es cuántos partidos hacen falta para que
la media propia de un equipo merezca la mitad del peso, y la media de la liga la
otra mitad.

    w(n) = n / (n + k)

Con k=10, veinte partidos ya pesan dos tercios. Con k=300, ni una temporada
entera llega a un cuarto — y eso, dicho sin rodeos, significa que ese número no
describe al equipo sino a la noche.

POR QUÉ NO HAY DOS CATEGORÍAS SINO UN CONTINUO. "Suerte" y "habilidad" no son
cajas: son los extremos de `w`. Un componente con k grande no es que sea
aleatorio, es que con las muestras que da una temporada de la NBA no se puede
distinguir de aleatorio. La frontera la pone el dato y no hay que defenderla.

QUÉ NO HACE. `k` sale del método de los momentos con 30 equipos por temporada,
así que también tiene error, y uno grande cuando la varianza verdadera es
pequeña — que es justo el caso de los porcentajes. Por eso `variance_components`
devuelve el `Reliability` del propio `k`. Un `k` sin su fiabilidad al lado
invita a construir encima de arena.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from nbastats.analysis.reliability import (
    Reliability,
    _estimate_tau_squared,
    reliability_for,
)

# Fronteras del continuo, en partidos. No son arbitrarias: media temporada y
# temporada entera son las dos muestras que un equipo puede llegar a tener.
K_HABILIDAD = 41
K_MIXTO = 82


@dataclass(frozen=True)
class Stability:
    key: str
    """'habilidad' | 'mixto' | 'suerte' | 'indistinguible'."""

    label: str
    note: str


@dataclass(frozen=True)
class VarianceComponents:
    """Descomposición de la varianza de un componente."""

    label: str
    n_units: int
    """Unidades comparadas (equipos-temporada)."""

    mean_n: float
    """Partidos por unidad, de media."""

    tau_squared: float
    """Varianza VERDADERA entre unidades, ya descontado el ruido."""

    within_var: float
    """Varianza de partido a partido dentro de una misma unidad."""

    k_games: float | None
    """Partidos para que la media propia pese la mitad. None si tau²=0."""

    reliability: Reliability
    stability: Stability
    note: str

    def weight(self, n: int) -> float:
        """Peso que merece la media observada de `n` partidos."""
        return shrinkage_weight(n, self.k_games)


def shrinkage_weight(n: int, k: float | None) -> float:
    """`n / (n + k)`, acotado a [0, 1].

    `k is None` significa que no se detectó diferencia real entre unidades: el
    peso es 0 y la media de la liga se lo lleva todo. Devolver 0 y no 0.5 es
    deliberado — cuando no hay señal, la respuesta honesta es "no sé nada de
    este equipo en particular", no "algo sabré".
    """
    if k is None or n <= 0:
        return 0.0
    return float(n / (n + k))


def describe_stability(k: float | None) -> Stability:
    """Traduce `k` a algo que se pueda leer.

    >>> describe_stability(8).key
    'habilidad'
    >>> describe_stability(300).key
    'suerte'
    >>> describe_stability(None).key
    'indistinguible'
    """
    if k is None:
        return Stability(
            "indistinguible",
            "Indistinguible",
            "No se detecta diferencia real entre equipos: toda la dispersión "
            "observada cabe dentro del ruido de muestreo.",
        )
    if k <= K_HABILIDAD:
        return Stability(
            "habilidad",
            "Habilidad",
            f"Se estabiliza en {k:.0f} partidos: media temporada basta para "
            "saber si un equipo es bueno en esto.",
        )
    if k <= K_MIXTO:
        return Stability(
            "mixto",
            "Mixto",
            f"Se estabiliza en {k:.0f} partidos: hace falta una temporada casi "
            "entera, y un solo partido no dice nada.",
        )
    return Stability(
        "suerte",
        "Sobre todo azar",
        f"Harían falta {k:.0f} partidos para que la media propia pesara la "
        "mitad — más de una temporada. En un partido suelto, esto es ruido.",
    )


def variance_components(
    groups: Mapping[str, Sequence[float]], *, label: str
) -> VarianceComponents:
    """Descompone la varianza de un componente entre unidades.

    `groups` es `{unidad: [valor en cada partido]}`, típicamente
    `{"BOS 2024-25": [0.38, 0.31, ...], ...}`. Cada valor es una observación de
    un partido.

    Se reutiliza `_estimate_tau_squared` de `reliability.py` en lugar de
    reimplementar el método de los momentos: es exactamente el mismo cálculo
    que ya sostiene el encogimiento de los splits, solo que agrupando por
    equipo-temporada en vez de por nivel de un split.
    """
    series = [
        np.asarray([v for v in vals if v is not None], dtype=float)
        for vals in groups.values()
    ]
    series = [s[np.isfinite(s)] for s in series]
    series = [s for s in series if s.size >= 2]

    if len(series) < 2:
        vacio = describe_stability(None)
        return VarianceComponents(
            label=label, n_units=len(series), mean_n=0.0, tau_squared=0.0,
            within_var=float("nan"), k_games=None,
            reliability=Reliability.INSUFICIENTE, stability=vacio,
            note="Menos de dos unidades con datos suficientes.",
        )

    means = np.array([s.mean() for s in series])
    ns = np.array([s.size for s in series])

    # Varianza intra agrupada, ponderada por grados de libertad. Promediar las
    # varianzas a secas daría el mismo peso a un equipo con 5 partidos y a otro
    # con 82.
    gl = ns - 1
    suma_gl = float(
        np.sum([np.var(s, ddof=1) * g for s, g in zip(series, gl, strict=True)])
    )
    within_var = suma_gl / float(np.sum(gl))

    tau_sq = _estimate_tau_squared(means, ns, within_var)
    k = float(within_var / tau_sq) if tau_sq > 0 else None
    estabilidad = describe_stability(k)
    fiabilidad = reliability_for(len(series))

    return VarianceComponents(
        label=label,
        n_units=len(series),
        mean_n=float(ns.mean()),
        tau_squared=float(tau_sq),
        within_var=within_var,
        k_games=k,
        reliability=fiabilidad,
        stability=estabilidad,
        note=(
            f"{estabilidad.note} Medido sobre {len(series)} equipos-temporada "
            f"de ~{ns.mean():.0f} partidos."
        ),
    )
