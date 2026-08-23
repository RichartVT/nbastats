"""Métricas normalizadas.

La regla que gobierna este módulo: **nunca comparar totales por partido.**

Si un jugador baja de 20 a 15 puntos, eso puede significar que juega peor o que
juega 8 minutos menos. Son diagnósticos opuestos y el total por partido no los
distingue. Todo el análisis de tendencias trabaja sobre las tasas de aquí.
"""

from __future__ import annotations

import math

# Coeficiente estándar de la NBA para estimar posesiones terminadas en tiros
# libres (aprox. el 44% de los intentos terminan una posesión: no cuentan los
# primeros tiros de un 1-y-1 ni los técnicos).
FT_POSSESSION_FACTOR = 0.44

# Minutos de referencia para per-36: un titular de rotación larga.
PER_36_MINUTES = 36
SECONDS_PER_36 = PER_36_MINUTES * 60


def _safe_div(numerator: float, denominator: float) -> float | None:
    """División que devuelve None en lugar de reventar o inventar ceros.

    Devolver None y no 0.0 es deliberado: 'no se puede calcular' (0 minutos
    jugados) y 'vale cero' (jugó y no anotó) son cosas distintas, y confundirlas
    contamina cualquier promedio posterior.
    """
    if denominator is None or numerator is None:
        return None
    if denominator == 0 or not math.isfinite(denominator):
        return None
    return numerator / denominator


def per_36(stat: float | None, seconds_played: int | None) -> float | None:
    """Escala una estadística a 36 minutos jugados."""
    if stat is None or not seconds_played:
        return None
    return stat * SECONDS_PER_36 / seconds_played


def per_100_possessions(stat: float | None, possessions: float | None) -> float | None:
    """Escala a 100 posesiones.

    Preferible a per-36 cuando se comparan épocas o equipos: absorbe las
    diferencias de ritmo, que entre 2018-19 y 2025-26 son grandes.
    """
    return None if stat is None else _safe_div(stat * 100, possessions)


def possessions_estimate(
    fga: int | None, fta: int | None, oreb: int | None, tov: int | None
) -> float | None:
    """Posesiones de un equipo en un partido (fórmula estándar).

    POS = FGA - OREB + TOV + 0.44 * FTA

    Solo tiene sentido a nivel de EQUIPO. Aplicarla a un jugador da un número
    sin significado, porque los rebotes ofensivos de sus compañeros extienden
    posesiones que él no terminó.
    """
    if None in (fga, fta, oreb, tov):
        return None
    return fga - oreb + tov + FT_POSSESSION_FACTOR * fta


def true_shooting_pct(
    pts: int | None, fga: int | None, fta: int | None
) -> float | None:
    """TS% = PTS / (2 * (FGA + 0.44 * FTA)).

    La mejor medida individual de eficiencia anotadora: es la única que pondera
    a la vez triples y tiros libres. Un jugador puede bajar su FG% y subir su
    TS% si cambia media distancia por triples, y eso es una mejora, no un
    declive.
    """
    if pts is None or fga is None or fta is None:
        return None
    attempts = 2 * (fga + FT_POSSESSION_FACTOR * fta)
    return _safe_div(pts, attempts)


def effective_fg_pct(
    fgm: int | None, fg3m: int | None, fga: int | None
) -> float | None:
    """eFG% = (FGM + 0.5 * FG3M) / FGA. Como el FG% pero contando que un triple vale más."""
    if fgm is None or fg3m is None:
        return None
    return _safe_div(fgm + 0.5 * fg3m, fga)


def usage_rate(
    fga: int | None,
    fta: int | None,
    tov: int | None,
    seconds_played: int | None,
    team_fga: int | None,
    team_fta: int | None,
    team_tov: int | None,
    team_seconds: int | None,
) -> float | None:
    """USG%: porcentaje de posesiones del equipo que termina el jugador mientras está en pista.

    Es la variable de control imprescindible para leer un declive: si el USG%
    cae junto con la producción, el jugador cambió de rol; si la producción cae
    con el USG% intacto, es rendimiento.
    """
    if None in (fga, fta, tov, seconds_played, team_fga, team_fta, team_tov, team_seconds):
        return None
    if not seconds_played or not team_seconds:
        return None

    player_plays = fga + FT_POSSESSION_FACTOR * fta + tov
    team_plays = team_fga + FT_POSSESSION_FACTOR * team_fta + team_tov
    # team_seconds son los segundos de los 5 puestos sumados; se divide entre 5
    # para llevarlo a "minutos de partido" comparables con los del jugador.
    return _safe_div(player_plays * (team_seconds / 5), seconds_played * team_plays)


def game_score(
    pts: int | None,
    fgm: int | None,
    fga: int | None,
    ftm: int | None,
    fta: int | None,
    oreb: int | None,
    dreb: int | None,
    stl: int | None,
    ast: int | None,
    blk: int | None,
    pf: int | None,
    tov: int | None,
) -> float | None:
    """Game Score de Hollinger: resumen de un partido en una sola cifra.

    Calibrado para que ~10 sea un partido promedio de titular y ~40 uno
    excepcional. Útil como serie temporal única cuando se quiere una vista
    general del rendimiento sin elegir una estadística concreta.
    """
    values = (pts, fgm, fga, ftm, fta, oreb, dreb, stl, ast, blk, pf, tov)
    if any(v is None for v in values):
        return None
    return (
        pts
        + 0.4 * fgm
        - 0.7 * fga
        - 0.4 * (fta - ftm)
        + 0.7 * oreb
        + 0.3 * dreb
        + stl
        + 0.7 * ast
        + 0.7 * blk
        - 0.4 * pf
        - tov
    )


def z_score(value: float | None, mean: float, std_dev: float) -> float | None:
    """Desviaciones típicas respecto a una referencia.

    Se usa siempre contra la liga de ESA temporada. La liga anotaba mucho más en
    2023-24 que en 2018-19; sin normalizar por año se confunde la inflación de
    la liga con la mejora del jugador.
    """
    if value is None or std_dev is None or std_dev == 0:
        return None
    return (value - mean) / std_dev
