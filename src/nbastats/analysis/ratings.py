"""Fuerza de un equipo, ajustada por la calidad de sus rivales.

POR QUÉ HACE FALTA. El diferencial de puntos sin ajustar acierta el ganador del
siguiente partido el 64,1 % de las veces, prácticamente lo mismo que la regla
tonta "gana el de mejor récord" (64,4 %). Y ya se comprobó que normalizar el
acierto de tiro no aporta nada: cinco formulaciones, ninguna mejora. Lo que le
falta a los dos es lo mismo — **contra quién se jugó**. Un +5 de diferencial
contra el calendario más duro de la liga y otro contra el más blando no valen
lo mismo, y ninguno de esos dos estimadores los distingue.

EL MODELO. Una fila por equipo y partido, con los puntos por 100 posesiones:

    anotados_por_100 = μ + O(equipo) − D(rival) + h·(local ? +1 : −1)

`O` es cuánto anota un equipo por encima de la media de la liga; `D`, cuánto
resta a lo que le anotan (más alto = mejor defensa). Se resuelve por mínimos
cuadrados con **filas aumentadas** para la regularización, en vez de con
`fit_regularized`: es forma cerrada, se ve exactamente qué columnas se penalizan
—las de equipo sí, `μ` y la localía no— y no hay optimizador que pueda no
converger.

DE DÓNDE SALE λ. No se busca a ciegas: es la `k` medida por `stability.py`
sobre estos mismos datos. Para el rating ofensivo la desviación típica entre
partidos es 11,2 y la diferencia real entre equipos 3,27, lo que da k≈12; para
la defensiva, k≈15. λ ES esa k: cuántos partidos de un equipo hacen falta para
que su propio dato pese lo mismo que la media de la liga. Un λ inventado sería
un parámetro más que justificar; este ya está medido.

IDENTIFICABILIDAD, Y QUÉ SIGNIFICA `league_mean`. `O` y `D` solo están
determinados hasta una constante: subir todos los ataques y todas las defensas a
la vez no cambia ninguna predicción. La regularización lo resuelve sola
empujando ambos hacia cero, así que **los efectos de equipo quedan centrados y
`league_mean` absorbe su media**. El resultado es que `league_mean` es la
anotación media real de la liga por 100 posesiones — se comprobó que coincide
con la media de las filas hasta el segundo decimal— y no un parámetro abstracto.
Es la parametrización útil, pero conviene saberlo: `league_mean` NO es
recuperable como "el μ del proceso generador" si los efectos de equipo tienen
media distinta de cero.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# λ por defecto: la k medida del rating ofensivo/defensivo (11,8 y 15,4).
LAMBDA_POR_DEFECTO = 13.0

# CUÁNTO SOBREVIVE UN EQUIPO A SU PROPIO VERANO. Medido sobre las 4 transiciones
# de temporada × 30 equipos (120 pares), regresando el rating de la temporada
# siguiente sobre el de la anterior:
#
#     ataque   ρ=+0,446 ± 0,074   pendiente 0,450
#     defensa  ρ=+0,517 ± 0,067   pendiente 0,554
#
# La defensa se hereda más que el ataque, que es lo que cabía esperar: depende
# más del sistema y menos de quién tenga la mano caliente. Las pendientes son lo
# que se usa, NO las correlaciones: la pendiente es la predicción insesgada del
# año siguiente, e incluye la regresión a la media que un equipo excepcional
# sufre por serlo.
PERSISTENCIA_ATAQUE = 0.450
PERSISTENCIA_DEFENSA = 0.554

# λ CONTRA EL PRIOR, y por qué es MAYOR que λ contra cero. λ = varianza dentro /
# varianza entre equipos. Al encoger hacia cero, la varianza "entre" es toda la
# dispersión de la liga (τ²). Al encoger hacia el prior, lo que queda por
# explicar es solo τ²(1−ρ²), que es menor — y λ, que la lleva en el
# denominador, sube. En otras palabras: un prior informativo merece MÁS peso
# que la nada, no menos. Sale de los mismos ρ de arriba, no de una búsqueda.
LAMBDA_PRIOR_ATAQUE = LAMBDA_POR_DEFECTO / (1 - 0.446**2)   # 16,2
LAMBDA_PRIOR_DEFENSA = LAMBDA_POR_DEFECTO / (1 - 0.517**2)  # 17,7


@dataclass(frozen=True)
class RatingRow:
    """Un equipo en un partido, ya normalizado por posesiones."""

    team_id: int
    opponent_id: int
    is_home: bool
    points_per_100: float
    weight: float = 1.0
    """Para dar menos peso a los partidos viejos. 1.0 = todos igual."""


@dataclass(frozen=True)
class TeamRating:
    team_id: int
    offense: float
    """Puntos por 100 que anota por encima de la media de la liga."""

    defense: float
    """Puntos por 100 que evita respecto a la media. POSITIVO = buena defensa."""

    games: int

    @property
    def net(self) -> float:
        return self.offense + self.defense


@dataclass(frozen=True)
class SeasonPrior:
    """Lo que se sabía de cada equipo ANTES de que la temporada empezara.

    Sale de los ratings finales de la temporada anterior, ya multiplicados por
    su persistencia. Es información legítima —está disponible antes del primer
    salto inicial— y por eso no es fuga; lo que sí lo sería es usar los ratings
    finales de la temporada EN CURSO, que es justo lo que `walk_forward` evita.
    """

    ratings: dict[int, tuple[float, float]]
    """team_id -> (ataque, defensa), ya encogidos por la persistencia."""

    league_mean: float
    home_advantage: float

    @classmethod
    def from_model(cls, modelo: RatingModel) -> SeasonPrior:
        return cls(
            ratings={
                t: (r.offense * PERSISTENCIA_ATAQUE, r.defense * PERSISTENCIA_DEFENSA)
                for t, r in modelo.ratings.items()
            },
            league_mean=modelo.league_mean,
            home_advantage=modelo.home_advantage,
        )

    def as_model(self) -> RatingModel:
        """El prior solo, sin datos de la temporada nueva.

        Es lo que se usa el primer día: mejor que no predecir nada, y muy
        explícitamente peor que el ajuste con partidos ya jugados.
        """
        return RatingModel(
            league_mean=self.league_mean,
            home_advantage=self.home_advantage,
            ratings={
                t: TeamRating(team_id=t, offense=o, defense=d, games=0)
                for t, (o, d) in self.ratings.items()
            },
            n_rows=0,
            lam=LAMBDA_POR_DEFECTO,
        )


@dataclass(frozen=True)
class RatingModel:
    league_mean: float
    home_advantage: float
    """Por 100 posesiones y por equipo. La ventaja en el MARGEN es el doble:
    el local suma esto y el visitante lo resta."""

    ratings: dict[int, TeamRating]
    n_rows: int
    lam: float

    def expected_margin_per_100(
        self, home_id: int, away_id: int, *, neutral: bool = False
    ) -> float | None:
        """Margen esperado por 100 posesiones, desde el local.

        Sale limpio porque los términos cruzados se cancelan:

            (O_local − D_visitante) − (O_visitante − D_local) + 2h
              = neto_local − neto_visitante + 2h

        En sede neutral se anula la localía: ahí no hay público propio, ni
        rutina, ni ausencia de viaje.
        """
        local = self.ratings.get(home_id)
        visitante = self.ratings.get(away_id)
        if local is None or visitante is None:
            return None
        ventaja = 0.0 if neutral else 2 * self.home_advantage
        return local.net - visitante.net + ventaja


def fit_ratings(
    rows: Sequence[RatingRow],
    *,
    lam: float = LAMBDA_POR_DEFECTO,
    prior: SeasonPrior | None = None,
) -> RatingModel | None:
    """Ajusta ataque y defensa de cada equipo, ajustados por rival.

    Con `prior`, las filas aumentadas dejan de empujar hacia cero y empujan
    hacia lo que el equipo era el año pasado: `√λ·(coef − prior) = 0`, que es lo
    mismo que poner `√λ·prior` en el término independiente. El cambio es de una
    línea y lo que compra es grande — sin prior, un equipo no tiene rating hasta
    su partido 20, y eso deja 1.246 partidos sin pronóstico.

    Un equipo que NO esté en el prior (una expansión, o el primer año que hay
    datos) sigue encogiendo hacia cero, que para él es lo correcto: la media de
    la liga es todo lo que se sabe.

    Devuelve `None` si no hay filas suficientes: con menos observaciones que
    parámetros el sistema no está determinado, y devolver ratings inventados
    sería peor que no devolver nada.
    """
    if not rows:
        return None

    equipos = sorted(
        {r.team_id for r in rows}
        | {r.opponent_id for r in rows}
        | (set(prior.ratings) if prior else set())
    )
    if len(equipos) < 2:
        return None

    indice = {t: i for i, t in enumerate(equipos)}
    n_equipos = len(equipos)
    # Columnas: [ataque × N | defensa × N | media | localía]
    col_media, col_local = 2 * n_equipos, 2 * n_equipos + 1
    n_col = 2 * n_equipos + 2

    X = np.zeros((len(rows), n_col))
    y = np.zeros(len(rows))
    peso = np.zeros(len(rows))

    for i, r in enumerate(rows):
        X[i, indice[r.team_id]] = 1.0
        X[i, n_equipos + indice[r.opponent_id]] = -1.0
        X[i, col_media] = 1.0
        X[i, col_local] = 1.0 if r.is_home else -1.0
        y[i] = r.points_per_100
        peso[i] = max(r.weight, 0.0)

    # Ponderación por raíz: minimizar Σ w·(y−ŷ)² equivale a mínimos cuadrados
    # ordinarios sobre las filas escaladas por √w.
    raiz = np.sqrt(peso)
    Xp = X * raiz[:, None]
    yp = y * raiz

    # Regularización por filas aumentadas: √λ en cada columna de equipo, y NADA
    # en la media ni en la localía. Penalizar la media empujaría el nivel de
    # anotación de la liga hacia cero, que no tiene ningún sentido.
    #
    # El objetivo de cada fila aumentada es `√λ·prior` (cero si no hay prior),
    # así que el ajuste minimiza λ·(coef − prior)² en vez de λ·coef².
    aumento = np.zeros((2 * n_equipos, n_col))
    objetivo = np.zeros(2 * n_equipos)
    for t in equipos:
        i_of, i_def = indice[t], n_equipos + indice[t]
        p_of, p_def = (prior.ratings.get(t, (0.0, 0.0)) if prior else (0.0, 0.0))
        lam_of = LAMBDA_PRIOR_ATAQUE if (prior and t in prior.ratings) else lam
        lam_def = LAMBDA_PRIOR_DEFENSA if (prior and t in prior.ratings) else lam
        aumento[i_of, i_of] = np.sqrt(lam_of)
        aumento[i_def, i_def] = np.sqrt(lam_def)
        objetivo[i_of] = np.sqrt(lam_of) * p_of
        objetivo[i_def] = np.sqrt(lam_def) * p_def

    A = np.vstack([Xp, aumento])
    b = np.concatenate([yp, objetivo])

    coef, *_ = np.linalg.lstsq(A, b, rcond=None)

    partidos: dict[int, int] = dict.fromkeys(equipos, 0)
    for r in rows:
        partidos[r.team_id] = partidos.get(r.team_id, 0) + 1

    return RatingModel(
        league_mean=float(coef[col_media]),
        home_advantage=float(coef[col_local]),
        ratings={
            t: TeamRating(
                team_id=t,
                offense=float(coef[indice[t]]),
                defense=float(coef[n_equipos + indice[t]]),
                games=partidos.get(t, 0),
            )
            for t in equipos
        },
        n_rows=len(rows),
        lam=lam,
    )


def decay_weights(
    ages_in_games: Sequence[float], *, half_life: float | None = None
) -> list[float]:
    """Peso que decae con la antigüedad: `0,5 ^ (edad / semivida)`.

    `half_life=None` devuelve todos los pesos a 1: es lo correcto por defecto,
    porque el decaimiento es un parámetro más y no se debe dar por bueno sin
    haberlo comparado fuera de muestra.

    >>> decay_weights([0, 20, 40], half_life=20)
    [1.0, 0.5, 0.25]
    """
    if half_life is None or half_life <= 0:
        return [1.0] * len(ages_in_games)
    return [float(0.5 ** (a / half_life)) for a in ages_in_games]
