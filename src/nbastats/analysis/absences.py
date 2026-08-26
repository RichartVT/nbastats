"""Cuánta rotación faltaba, y qué vale eso.

LA SEÑAL MÁS FUERTE QUE HABÍA SIN USAR, y no costó una sola petición: sale de
cruzar quién suele jugar con quién jugó cada noche.

| Minutos habituales fuera | Partidos | Victorias | Margen medio |
|---|---|---|---|
| 0–20 | 1.491 | **59,4 %** | +4,2 |
| 20–40 | 2.029 | 57,6 % | +2,5 |
| 40–60 | 2.476 | 55,3 % | +1,6 |
| 60–80 | 2.306 | 50,2 % | +0,2 |
| 80–100 | 1.776 | 46,9 % | −1,3 |
| 100+ | 3.126 | **38,0 %** | −4,4 |

Monótono en los seis tramos y en las dos columnas. Controlando por la fuerza de
los dos equipos, cada minuto de rotación ausente vale **0,0373 puntos de margen**
(EE 0,0031, t=11,9, p=2,3e-32): unos 3,7 puntos por cada 100 minutos fuera. Añade
1,75 puntos de varianza explicada por encima de los ratings, así que no es algo
que los ratings ya supieran.

DÓNDE VA Y DÓNDE NO, que es lo importante:

- **Explicación: sí, y arriba.** Un equipo sin sus dos mejores no tuvo mala
  suerte: jugó con otro equipo. Va en el nivel de información previa al partido,
  nunca en el bloque de suerte.
- **Backtest del pronóstico: NO.** Por partida doble. Que un jugador no aparezca
  en el box score se sabe DESPUÉS del partido, y además los "minutos habituales"
  se calculan con la temporada entera, que incluye partidos posteriores. Meterlo
  en el walk-forward subiría las métricas y las dejaría mintiendo.
- **Simulador: sí, como entrada del usuario**, y como ajuste SEPARADO del número
  calibrado. El modelo de probabilidad no se entrenó con esto; presentarlo como
  si fuera parte de él rompería la calibración que sí está medida.

EL UMBRAL DE ROTACIÓN ES UNA DECISIÓN, NO UN DESCUBRIMIENTO. "Rotación" son los
jugadores de 10+ minutos de media, que es la definición convencional. Se eligió
por eso y no por el resultado: el recorrido del gradiente va de 15,1 pp (sin
umbral) a 23,5 pp (umbral de 15 minutos), así que el titular depende de dónde se
ponga la raya y conviene decirlo en vez de enseñar el número más vistoso.
"""

from __future__ import annotations

from dataclasses import dataclass

# Puntos de margen por minuto habitual ausente, controlando por la fuerza de
# ambos equipos. Medido sobre 6.140 partidos de temporada regular.
PUNTOS_POR_MINUTO = 0.0373

# Minutos de media que hacen a un jugador "de la rotación".
MINUTOS_ROTACION = 10.0


@dataclass(frozen=True)
class AbsenceIndex:
    """Lo que le faltaba a un equipo esa noche."""

    minutes: float
    """Suma de minutos habituales de los ausentes de la rotación."""

    players: int
    level: str
    """Clave estable para la interfaz: `completa`, `leve`, `notable`, `grave`."""

    label: str
    margin_cost: float
    """Puntos de margen que cuesta, en negativo. Es una estimación media, no una
    predicción de este partido: dos ausencias de 20 minutos no duelen lo mismo si
    una es la del base titular."""

    @property
    def is_depleted(self) -> bool:
        return self.level in ("notable", "grave")


# Los cortes son los del gradiente medido, no redondeos elegidos a ojo.
_NIVELES: tuple[tuple[float, str, str], ...] = (
    (20.0, "completa", "Plantilla al completo"),
    (60.0, "leve", "Alguna baja"),
    (100.0, "notable", "Rotación mermada"),
    (float("inf"), "grave", "Rotación diezmada"),
)


def describe_absences(minutes: float | None, players: int | None) -> AbsenceIndex:
    """Convierte los minutos ausentes en algo que se pueda enseñar.

    `None` se trata como cero y NO como "sin datos": la derivación cubre los
    13.204 equipo-partido, así que un hueco aquí sería un fallo de la derivación
    y no una ausencia de información. Si algún día deja de ser cierto, esto
    mentiría en la dirección optimista.

    >>> describe_absences(0, 0).level
    'completa'
    >>> describe_absences(140, 3).level
    'grave'
    >>> round(describe_absences(100, 2).margin_cost, 2)
    -3.73
    """
    m = float(minutes or 0.0)
    for corte, nivel, etiqueta in _NIVELES:
        if m < corte:
            return AbsenceIndex(
                minutes=m,
                players=int(players or 0),
                level=nivel,
                label=etiqueta,
                margin_cost=-m * PUNTOS_POR_MINUTO,
            )
    raise AssertionError("el último corte es infinito")  # pragma: no cover


def margin_adjustment(home_minutes: float, away_minutes: float) -> float:
    """Puntos que las ausencias mueven el margen, desde el local.

    Positivo = favorece al local, porque al visitante le falta más gente.

    >>> round(margin_adjustment(0, 100), 2)
    3.73
    >>> margin_adjustment(50, 50)
    0.0
    """
    return (float(away_minutes) - float(home_minutes)) * PUNTOS_POR_MINUTO
