"""Qué debió pasar en un partido, y qué lo torció.

"Este equipo debió ganar" no significa nada mirando el marcador: el marcador es
lo que pasó. Significa algo cuando se separa lo que un equipo **controla** de lo
que le **ocurrió**, y esa separación no es una opinión — sale de
`analysis/stability.py`, que mide cuántos partidos hace falta para que la media
propia de un equipo pese la mitad:

    Triples que CONCEDES        k = 8    -> lo eliges tú
    Que esos triples ENTREN     k = 150  -> es la noche

QUÉ SE SUSTITUYE Y QUÉ NO. Los volúmenes se dejan intactos: cuántos triples se
tiran y cuántos se conceden es decisión, y se mide como la cosa más estable del
juego (k=3 y k=8). Lo que se sustituye por su norma es el **acierto**, que es lo
que ni se elige ni se repite. Esa asimetría es el diseño entero.

    puntos_esperados = 2·FG2A·q2 + 3·FG3A·q3 + FTA·qft

POR QUÉ EL DESGLOSE CIERRA EXACTO. Porque los puntos son, por identidad
contable, `2·FGM + FG3M + FTM` — comprobado en las 13.204 filas de equipo y en
las 140.932 de jugador, sin una sola excepción. Y porque al mantener el volumen
fijo, cada término de suerte es LINEAL en el acierto sustituido:

    suerte_3 = 3 · FG3A · (fg3% − q3)

No hay términos cruzados, no hay que repartir interacciones, no hace falta
Shapley ni discutir el orden de sustitución. La suma de los componentes ES la
diferencia entre el margen real y el esperado, hasta el último decimal — y hay
un test que lo exige sobre los 12.300 equipo-partido.

LO QUE ESTO NO ES. No es "quién merecía ganar". Es "qué predecían las partes que
se repiten". Un equipo que pierde con el desglose a favor no fue robado: tuvo
una mala noche en lo que nadie controla. Y los componentes **se cancelan entre
sí** —quien tira mucho de tres genera menos rebote ofensivo—, así que una barra
suelta no es un contrafactual: no se puede decir "sin eso habrían ganado por 8".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Los tiros libres cuentan 0,44 por posesión: es el factor estándar que ya usa
# `rates.possessions_estimate`, y viene de que no todo tiro libre termina una.
FT_POSSESSION_FACTOR = 0.44


@dataclass(frozen=True)
class TeamBox:
    """Lo que hizo un equipo en un partido. La entrada mínima del motor."""

    pts: int
    fgm: int
    fga: int
    fg3m: int
    fg3a: int
    ftm: int
    fta: int
    oreb: int
    dreb: int
    tov: int

    @property
    def fg2m(self) -> int:
        """Tiros de 2 anotados. La fuente da el total y los triples, no esto."""
        return self.fgm - self.fg3m

    @property
    def fg2a(self) -> int:
        return self.fga - self.fg3a

    @property
    def efg_pct(self) -> float | None:
        """eFG%: el triple vale 1,5 veces un tiro de 2 porque da 1,5 veces los
        puntos. Un 45% de triples y un 45% de dobles no valen lo mismo."""
        return (self.fgm + 0.5 * self.fg3m) / self.fga if self.fga else None


@dataclass(frozen=True)
class ShootingNorms:
    """El acierto que cabía esperar, por tipo de tiro.

    `n_games` viaja con las normas y no es decorativo: una norma sacada de 6
    partidos y otra de 70 se escriben igual y no valen lo mismo. Quien consuma
    esto debe pasarla por `reliability_for()` antes de afirmar nada.
    """

    fg2_pct: float
    fg3_pct: float
    ft_pct: float
    n_games: int = 0


@dataclass(frozen=True)
class LuckComponent:
    """Un sumando del desglose, ya en puntos."""

    key: str
    label: str
    points: float
    """Positivo = le salió mejor de lo que cabía esperar."""

    detail: str


@dataclass(frozen=True)
class TeamLuck:
    """Cuánto se desvió un equipo de su acierto esperado, en puntos."""

    expected_points: float
    actual_points: int
    components: list[LuckComponent]

    @property
    def total(self) -> float:
        """Puntos que le regaló o le quitó la noche."""
        return self.actual_points - self.expected_points


@dataclass(frozen=True)
class MarginAttribution:
    """El desglose completo de un partido, desde el lado del equipo local."""

    actual_margin: int
    expected_margin: float
    home: TeamLuck
    away: TeamLuck
    components: list[LuckComponent]
    unexplained_pts: float
    """Debe ser 0. Existe para que un error de atribución no viva en silencio."""

    @property
    def swing(self) -> float:
        """Cuánto torció la noche el resultado. Positivo = favoreció al local."""
        return self.actual_margin - self.expected_margin

    @property
    def flipped(self) -> bool:
        """El desglose señalaba a un ganador y ganó el otro.

        Es la definición operativa de "debió ganar y perdió", y por eso se
        calcula aquí en vez de dejarla a criterio de cada pantalla.
        """
        return (self.expected_margin > 0) != (self.actual_margin > 0) and (
            self.expected_margin != 0 and self.actual_margin != 0
        )


def expected_points(box: TeamBox, norms: ShootingNorms) -> float:
    """Puntos que cabía esperar con ESE volumen de tiro y el acierto normal."""
    return (
        2 * box.fg2a * norms.fg2_pct
        + 3 * box.fg3a * norms.fg3_pct
        + box.fta * norms.ft_pct
    )


def team_luck(box: TeamBox, norms: ShootingNorms) -> TeamLuck:
    """Descompone la desviación de un equipo respecto a su acierto esperado.

    Cada componente es `volumen · (acierto_real − acierto_esperado) · valor`, y
    los tres suman exactamente `puntos_reales − puntos_esperados` porque los
    puntos son `2·FG2M + 3·FG3M + FTM` por identidad.
    """
    componentes = [
        _componente(
            "triples", "Acierto en triples", 3, box.fg3m, box.fg3a, norms.fg3_pct
        ),
        _componente(
            "tiros_2", "Acierto en tiros de 2", 2, box.fg2m, box.fg2a, norms.fg2_pct
        ),
        _componente(
            "libres", "Acierto en tiros libres", 1, box.ftm, box.fta, norms.ft_pct
        ),
    ]
    return TeamLuck(
        expected_points=expected_points(box, norms),
        actual_points=box.pts,
        components=componentes,
    )


def _componente(
    key: str, label: str, valor: int, hechos: int, intentos: int, norma: float
) -> LuckComponent:
    esperados = intentos * norma
    puntos = valor * (hechos - esperados)
    if intentos == 0:
        detalle = "Sin intentos."
    else:
        detalle = (
            f"{hechos}/{intentos} ({hechos / intentos:.1%}) frente a un "
            f"{norma:.1%} esperado: {esperados:.1f} esperados, "
            f"{hechos - esperados:+.1f}."
        )
    return LuckComponent(key=key, label=label, points=puntos, detail=detalle)


def attribute_margin(
    home: TeamBox,
    home_norms: ShootingNorms,
    away: TeamBox,
    away_norms: ShootingNorms,
) -> MarginAttribution:
    """Reparte la diferencia entre el margen real y el esperado.

    El signo es SIEMPRE desde el local: un componente positivo empujó el
    marcador hacia el local, aunque sea un fallo del visitante. Sin esa
    convención los sumandos no se pueden sumar entre equipos.
    """
    suerte_local = team_luck(home, home_norms)
    suerte_visitante = team_luck(away, away_norms)

    componentes = [
        LuckComponent(
            key=f"local_{c.key}",
            label=f"{c.label} (local)",
            points=c.points,
            detail=c.detail,
        )
        for c in suerte_local.components
    ] + [
        # El acierto del visitante entra con signo cambiado: que él acierte
        # empuja el marcador en contra del local.
        LuckComponent(
            key=f"visitante_{c.key}",
            label=f"{c.label} (visitante)",
            points=-c.points,
            detail=c.detail,
        )
        for c in suerte_visitante.components
    ]

    margen_real = home.pts - away.pts
    margen_esperado = suerte_local.expected_points - suerte_visitante.expected_points

    return MarginAttribution(
        actual_margin=margen_real,
        expected_margin=margen_esperado,
        home=suerte_local,
        away=suerte_visitante,
        components=componentes,
        unexplained_pts=(margen_real - margen_esperado) - sum(c.points for c in componentes),
    )


# =========================================================================
# Four Factors de Dean Oliver
# =========================================================================


@dataclass(frozen=True)
class FourFactors:
    """Los cuatro factores de un equipo en un partido.

    No son un modelo: son un cambio de variable sobre la identidad de las
    posesiones. Por eso explican casi todo el margen — y por eso ese "casi
    todo" no es un descubrimiento, es contabilidad.
    """

    efg_pct: float | None
    tov_rate: float | None
    oreb_pct: float | None
    ft_rate: float | None
    possessions: float


def four_factors(box: TeamBox, opponent: TeamBox) -> FourFactors:
    """Calcula los cuatro factores. Necesita al rival para el rebote ofensivo.

    Se usa la fórmula de posesiones (`FGA − OREB + TOV + 0,44·FTA`) y no el dato
    de posesiones de la API. La diferencia típica es de 1-2 posesiones, pero
    solo con la fórmula la identidad de los cuatro factores cierra exactamente,
    que es lo que se viene a buscar aquí. El dato de la API se mantiene para el
    ritmo y para cualquier cifra que se compare con NBA.com.
    """
    poss = box.fga - box.oreb + box.tov + FT_POSSESSION_FACTOR * box.fta
    rebotes_disponibles = box.oreb + opponent.dreb
    return FourFactors(
        efg_pct=box.efg_pct,
        tov_rate=box.tov / poss if poss else None,
        oreb_pct=box.oreb / rebotes_disponibles if rebotes_disponibles else None,
        ft_rate=box.fta / box.fga if box.fga else None,
        possessions=poss,
    )


def exact_product_split(
    x: float, x_hat: float, y: float, y_hat: float
) -> tuple[float, float]:
    """Reparte `x·y − x̂·ŷ` entre sus dos factores, sin residuo.

        x·y − x̂·ŷ = ((y+ŷ)/2)·(x−x̂) + ((x+x̂)/2)·(y−ŷ)

    Es una identidad algebraica, no una aproximación, y coincide con el valor de
    Shapley para dos factores. Sirve para atribuir un cambio en un producto —
    posesiones × eficiencia, intentos × acierto— sin que sobre un término
    cruzado que alguien tendría que repartir a ojo.

    >>> a, b = exact_product_split(10, 8, 3, 2)
    >>> round(a + b, 10) == 10 * 3 - 8 * 2
    True
    """
    efecto_x = ((y + y_hat) / 2) * (x - x_hat)
    efecto_y = ((x + x_hat) / 2) * (y - y_hat)
    return efecto_x, efecto_y


def shrunk_norm(
    made: int, attempted: int, league: float, prior_attempts: float
) -> float:
    """Acierto propio encogido hacia la liga, por beta-binomial.

    `prior_attempts` es cuántos intentos hacen falta para que el acierto propio
    pese la mitad — el mismo concepto que la `k` de `stability.py`, pero contado
    en intentos en vez de en partidos.

    Sirve para las normas de tiro cuando la muestra es corta: al principio de
    temporada, o cuando la norma se pondera por los jugadores que tiraron esa
    noche. Sin esto, un equipo con 20 triples lanzados tendría una "norma"
    dominada por el ruido.

    >>> round(shrunk_norm(0, 0, 0.36, 100), 4)
    0.36
    >>> shrunk_norm(50, 100, 0.36, 100)
    0.43
    """
    if attempted <= 0:
        return league
    return (made + prior_attempts * league) / (attempted + prior_attempts)


def league_norms(boxes: Sequence[TeamBox]) -> ShootingNorms:
    """Norma de liga a partir de un conjunto de partidos.

    Se agrega sobre TOTALES, nunca promediando los porcentajes de cada partido:
    promediar razones da un número distinto y equivocado, porque pondera igual
    un partido de 40 triples y uno de 12.
    """
    fg2m = sum(b.fg2m for b in boxes)
    fg2a = sum(b.fg2a for b in boxes)
    fg3m = sum(b.fg3m for b in boxes)
    fg3a = sum(b.fg3a for b in boxes)
    ftm = sum(b.ftm for b in boxes)
    fta = sum(b.fta for b in boxes)
    return ShootingNorms(
        fg2_pct=fg2m / fg2a if fg2a else 0.0,
        fg3_pct=fg3m / fg3a if fg3a else 0.0,
        ft_pct=ftm / fta if fta else 0.0,
        n_games=len(boxes),
    )
