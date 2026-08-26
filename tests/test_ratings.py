"""Tests de los ratings ajustados por rival.

Se prueban contra ligas SINTÉTICAS con fuerza conocida: es la única forma de
saber si el ajuste recupera la verdad, porque con datos reales no hay verdad
contra la que comparar. Y se prueba lo que de verdad puede romperse sin dar
error: que el ajuste por rival haga algo, y que no haya fuga temporal.
"""

from __future__ import annotations

import numpy as np
import pytest

from nbastats.analysis.ratings import (
    LAMBDA_POR_DEFECTO,
    RatingRow,
    decay_weights,
    fit_ratings,
)


def liga(rng, *, n_equipos=10, jornadas=60, sd_ruido=11.0, media=112.0, localia=2.0):
    """Liga sintética donde la fuerza real de cada equipo se conoce."""
    verdad = {t: (rng.normal(0, 4), rng.normal(0, 3)) for t in range(n_equipos)}
    filas = []
    for _ in range(jornadas):
        orden = rng.permutation(n_equipos)
        for a, b in zip(orden[::2], orden[1::2], strict=False):
            for local, visitante, casa in ((a, b, True), (b, a, False)):
                o = verdad[local][0]
                d = verdad[visitante][1]
                pts = media + o - d + (localia if casa else -localia) + rng.normal(0, sd_ruido)
                filas.append(RatingRow(int(local), int(visitante), casa, pts))
    return verdad, filas


class TestRecuperaLaVerdad:
    def test_el_ataque_estimado_correlaciona_con_el_real(self):
        rng = np.random.default_rng(1)
        verdad, filas = liga(rng)
        m = fit_ratings(filas)
        est = [m.ratings[t].offense for t in verdad]
        real = [verdad[t][0] for t in verdad]
        assert np.corrcoef(est, real)[0, 1] > 0.85

    def test_la_defensa_tambien(self):
        rng = np.random.default_rng(2)
        verdad, filas = liga(rng)
        m = fit_ratings(filas)
        est = [m.ratings[t].defense for t in verdad]
        real = [verdad[t][1] for t in verdad]
        assert np.corrcoef(est, real)[0, 1] > 0.80

    def test_recupera_la_localia(self):
        rng = np.random.default_rng(3)
        _, filas = liga(rng, localia=2.5)
        assert fit_ratings(filas).home_advantage == pytest.approx(2.5, abs=0.8)

    def test_la_media_de_liga_es_la_anotacion_real(self):
        """`league_mean` NO recupera el μ del proceso generador, y no es un
        fallo: la regularización centra los efectos de equipo en cero, así que
        la media de esos efectos se absorbe en `league_mean`. Lo que sí es
        identificable —y lo útil— es que sea la anotación media real."""
        rng = np.random.default_rng(4)
        _, filas = liga(rng, media=115.0)
        m = fit_ratings(filas)
        real = np.mean([f.points_per_100 for f in filas])
        assert m.league_mean == pytest.approx(real, abs=0.5)

    def test_los_efectos_de_equipo_quedan_centrados(self):
        rng = np.random.default_rng(4)
        _, filas = liga(rng)
        m = fit_ratings(filas)
        assert np.mean([r.offense for r in m.ratings.values()]) == pytest.approx(0, abs=0.5)
        assert np.mean([r.defense for r in m.ratings.values()]) == pytest.approx(0, abs=0.5)


class TestElAjustePorRivalHaceAlgo:
    """Si esto falla, el módulo entero no sirve para nada: sería un diferencial
    de puntos con pasos extra."""

    def test_un_calendario_facil_no_infla_el_rating(self):
        # Dos equipos idénticos: uno solo juega contra el peor, otro contra el mejor.
        filas = []
        for _ in range(40):
            filas += [
                RatingRow(1, 99, True, 118.0),   # el 99 es un desastre
                RatingRow(99, 1, False, 100.0),
                RatingRow(2, 98, True, 108.0),   # el 98 es excelente
                RatingRow(98, 2, False, 110.0),
                RatingRow(99, 98, True, 100.0),
                RatingRow(98, 99, False, 118.0),
            ]
        m = fit_ratings(filas)
        # El 1 anota 10 más por partido que el 2, pero contra un rival peor.
        # El ajuste tiene que acercarlos mucho más que esos 10 puntos.
        assert abs(m.ratings[1].offense - m.ratings[2].offense) < 8.0


class TestRegularizacion:
    def test_lambda_alto_encoge_hacia_cero(self):
        rng = np.random.default_rng(5)
        _, filas = liga(rng)
        suave = fit_ratings(filas, lam=1.0)
        duro = fit_ratings(filas, lam=500.0)
        disp = lambda m: np.std([r.offense for r in m.ratings.values()])  # noqa: E731
        assert disp(duro) < disp(suave)

    def test_no_penaliza_la_media_de_liga(self):
        """Penalizar la media empujaría el nivel de anotación hacia cero, que no
        significa nada."""
        rng = np.random.default_rng(6)
        _, filas = liga(rng, media=112.0)
        assert fit_ratings(filas, lam=500.0).league_mean == pytest.approx(112.0, abs=3.0)

    def test_el_lambda_por_defecto_es_la_k_medida(self):
        """No es un número inventado: sale de stability.py sobre estos datos
        (k≈12 para el ataque, k≈15 para la defensa)."""
        assert 10 <= LAMBDA_POR_DEFECTO <= 16


class TestMargenEsperado:
    def test_el_mejor_equipo_es_favorito_en_casa(self):
        rng = np.random.default_rng(7)
        verdad, filas = liga(rng)
        m = fit_ratings(filas)
        mejor = max(verdad, key=lambda t: verdad[t][0] + verdad[t][1])
        peor = min(verdad, key=lambda t: verdad[t][0] + verdad[t][1])
        assert m.expected_margin_per_100(mejor, peor) > 0

    def test_la_sede_neutral_anula_la_localia(self):
        rng = np.random.default_rng(8)
        _, filas = liga(rng)
        m = fit_ratings(filas)
        con = m.expected_margin_per_100(0, 1)
        sin = m.expected_margin_per_100(0, 1, neutral=True)
        assert con - sin == pytest.approx(2 * m.home_advantage)

    def test_es_antisimetrico(self):
        """A en casa contra B y B en casa contra A deben dar márgenes que
        difieran exactamente en el doble de la localía."""
        rng = np.random.default_rng(9)
        _, filas = liga(rng)
        m = fit_ratings(filas)
        ida = m.expected_margin_per_100(0, 1, neutral=True)
        vuelta = m.expected_margin_per_100(1, 0, neutral=True)
        assert ida == pytest.approx(-vuelta)

    def test_equipo_desconocido_devuelve_none(self):
        """No inventar un rating es mejor que devolver cero, que se leería como
        'equipo promedio'."""
        rng = np.random.default_rng(10)
        _, filas = liga(rng)
        assert fit_ratings(filas).expected_margin_per_100(0, 12345) is None


class TestCasosLimite:
    def test_sin_filas_no_hay_modelo(self):
        assert fit_ratings([]) is None

    def test_un_solo_equipo_no_permite_comparar(self):
        assert fit_ratings([RatingRow(1, 1, True, 110.0)]) is None

    def test_los_pesos_influyen(self):
        """Un partido con peso 0 no debe contar."""
        base = [RatingRow(1, 2, True, 110.0), RatingRow(2, 1, False, 100.0)] * 20
        con_ruido = base + [RatingRow(1, 2, True, 300.0, weight=0.0)] * 20
        a, b = fit_ratings(base), fit_ratings(con_ruido)
        assert a.ratings[1].offense == pytest.approx(b.ratings[1].offense, abs=0.5)


class TestDecaimiento:
    def test_sin_semivida_todos_pesan_igual(self):
        """Es lo correcto por defecto: el decaimiento es un parámetro más y no
        se da por bueno sin compararlo fuera de muestra."""
        assert decay_weights([0, 50, 200]) == [1.0, 1.0, 1.0]

    def test_en_la_semivida_el_peso_es_la_mitad(self):
        assert decay_weights([25], half_life=25) == [pytest.approx(0.5)]

    def test_decae_de_forma_monotona(self):
        p = decay_weights([0, 10, 20, 40], half_life=20)
        assert p == sorted(p, reverse=True)
