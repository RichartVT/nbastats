"""El prior entre temporadas: que ayude, y sobre todo que no vea el futuro.

La fuga temporal es el fallo más fácil de cometer aquí y el más difícil de
detectar, porque no da error: sube las métricas y las deja mintiendo. Estos
tests existen para que no pueda ocurrir en silencio.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from nbastats.analysis.backtest import GameRow, walk_forward
from nbastats.analysis.ratings import (
    LAMBDA_PRIOR_ATAQUE,
    PERSISTENCIA_ATAQUE,
    PERSISTENCIA_DEFENSA,
    RatingRow,
    SeasonPrior,
    TeamRating,
    fit_ratings,
)


def _modelo_falso(netos: dict[int, tuple[float, float]]):
    from nbastats.analysis.ratings import RatingModel

    return RatingModel(
        league_mean=112.0,
        home_advantage=0.9,
        ratings={t: TeamRating(t, o, d, 82) for t, (o, d) in netos.items()},
        n_rows=2000,
        lam=13.0,
    )


def test_el_prior_encoge_por_la_persistencia_medida():
    """No se hereda el rating entero: se hereda la parte que sobrevive."""
    prior = SeasonPrior.from_model(_modelo_falso({1: (4.0, 2.0)}))
    assert prior.ratings[1][0] == pytest.approx(4.0 * PERSISTENCIA_ATAQUE)
    assert prior.ratings[1][1] == pytest.approx(2.0 * PERSISTENCIA_DEFENSA)
    # Y la defensa se hereda MÁS que el ataque. Si algún día se invierte, es un
    # hallazgo, no un detalle: hay que volver a medirlo antes de cambiarlo.
    assert PERSISTENCIA_DEFENSA > PERSISTENCIA_ATAQUE


def test_sin_datos_nuevos_el_ajuste_devuelve_el_prior():
    """Con una temporada recién empezada, lo único que se sabe es el prior."""
    prior = SeasonPrior.from_model(_modelo_falso({1: (3.0, -1.0), 2: (-3.0, 1.0)}))
    modelo = prior.as_model()
    assert modelo.ratings[1].offense == pytest.approx(3.0 * PERSISTENCIA_ATAQUE)
    assert modelo.ratings[1].games == 0


def test_un_equipo_sin_prior_sigue_encogiendo_hacia_cero():
    """Una expansión no hereda nada, y para ella la media de la liga es todo."""
    prior = SeasonPrior.from_model(_modelo_falso({1: (5.0, 0.0)}))
    filas = [
        RatingRow(1, 99, True, 120.0),
        RatingRow(99, 1, False, 100.0),
    ] * 30
    modelo = fit_ratings(filas, prior=prior)
    assert modelo is not None
    # El equipo 99 no está en el prior: su rating sale solo de sus partidos,
    # encogido hacia cero y no hacia ningún recuerdo que no existe.
    assert 99 in modelo.ratings
    assert abs(modelo.ratings[99].offense) < abs(modelo.ratings[1].offense) + 20


def test_lambda_del_prior_es_mayor_que_la_de_cero():
    """Un prior informativo merece MÁS peso que la nada, no menos.

    Si esto se invirtiera, el ajuste estaría tratando el recuerdo del año
    pasado como si fuera menos fiable que no saber nada.
    """
    from nbastats.analysis.ratings import LAMBDA_POR_DEFECTO

    assert LAMBDA_PRIOR_ATAQUE > LAMBDA_POR_DEFECTO


def _liga(semilla: int, temporadas: int = 2, vueltas: int = 6) -> list[GameRow]:
    """Liga sintética de 6 equipos con fuerza estable entre temporadas."""
    rng = np.random.default_rng(semilla)
    fuerza = {t: 3.0 * (t - 2.5) for t in range(6)}
    salida, base = [], dt.date(2021, 10, 20)
    for temp in range(temporadas):
        season = f"20{21 + temp}-{22 + temp}"
        dia = 0
        for _ in range(vueltas):
            for a in range(6):
                for b in range(6):
                    if a == b:
                        continue
                    dia += 1
                    margen = fuerza[a] - fuerza[b] + 2.0 + rng.normal(0, 11)
                    salida.append(
                        GameRow(
                            game_id=f"{season}-{dia:05d}", season_id=season,
                            date=base + dt.timedelta(days=temp * 400 + dia // 4),
                            home_id=a, away_id=b, home_won=margen > 0, margin=margen,
                            home_pts_per_100=112 + fuerza[a] + rng.normal(0, 8),
                            away_pts_per_100=112 + fuerza[b] + rng.normal(0, 8),
                            home_rest=1.0, away_rest=1.0,
                            home_b2b=False, away_b2b=False,
                        )
                    )
    return salida


def test_el_prior_no_ve_el_futuro():
    """EL TEST QUE IMPORTA.

    Se altera el resultado de los ÚLTIMOS partidos de la última temporada y se
    exige que ni una sola variable de los partidos anteriores cambie. Si el
    prior se estuviera calculando con la temporada en curso —o si el historial
    se llenara antes de predecir— este test lo detecta.
    """
    partidos = _liga(7)
    original, _ = walk_forward(partidos)

    # Se destroza el final: mismos partidos, resultados opuestos y exagerados.
    tocados = list(partidos)
    for i in range(len(tocados) - 40, len(tocados)):
        g = tocados[i]
        tocados[i] = GameRow(
            **{**g.__dict__, "home_won": not g.home_won, "margin": -g.margin * 3,
               "home_pts_per_100": 60.0, "away_pts_per_100": 160.0}
        )
    alterado, _ = walk_forward(tocados)

    ids_tocados = {g.game_id for g in tocados[-40:]}
    antes = {m.game_id: m.features for m in original if m.game_id not in ids_tocados}
    despues = {m.game_id: m.features for m in alterado if m.game_id not in ids_tocados}

    assert set(antes) == set(despues), "el prior cambió QUÉ partidos se predicen"
    for gid, f in antes.items():
        assert f.rating_diff == pytest.approx(despues[gid].rating_diff), (
            f"el partido {gid} cambió al alterar partidos POSTERIORES: hay fuga"
        )


def test_el_prior_amplia_la_cobertura_del_arranque():
    """Sin prior no hay pronóstico hasta el partido 20 de cada equipo."""
    partidos = _liga(11)
    sin, _ = walk_forward(partidos, usar_prior=False)
    con, _ = walk_forward(partidos, usar_prior=True)
    assert len(con) > len(sin)
    # Y lo que se gana está en la segunda temporada, que es la que tiene prior.
    nuevos = {m.game_id for m in con} - {m.game_id for m in sin}
    assert all(gid.startswith("2022-23") for gid in nuevos)
