"""Tests del modelo de probabilidad.

Contra mundos sintéticos con coeficientes conocidos: es la única forma de saber
si el ajuste recupera la verdad. Y se prueba la regla de la casa — que las dos
rutas independientes coincidan antes de afirmar una probabilidad.
"""

from __future__ import annotations

import numpy as np
import pytest

from nbastats.analysis.forecast import GameFeatures, fit_win_model


def mundo(rng, n=4000, *, beta_rating=1.05, localia=2.2, sd=13.0):
    rd = rng.normal(0, 6, n)
    rest = rng.integers(-2, 3, n).astype(float)
    b2b = rng.integers(-1, 2, n).astype(float)
    margen = beta_rating * rd + localia + 0.4 * rest + 1.2 * b2b + rng.normal(0, sd, n)
    feats = [
        GameFeatures(float(a), True, float(b), float(c))
        for a, b, c in zip(rd, rest, b2b, strict=True)
    ]
    return feats, margen, margen > 0


class TestRecuperaLaVerdad:
    def test_estima_bien_la_dispersion_del_margen(self):
        """σ es lo que convierte puntos en probabilidad, y también lo que dice
        cuánta incertidumbre es irreducible."""
        rng = np.random.default_rng(0)
        m = fit_win_model(*mundo(rng, sd=13.0))
        assert m.sigma == pytest.approx(13.0, abs=0.6)

    def test_estima_bien_el_efecto_del_rating(self):
        rng = np.random.default_rng(1)
        m = fit_win_model(*mundo(rng, beta_rating=1.05))
        assert m.margin_params["rating_diff"] == pytest.approx(1.05, abs=0.15)

    def test_estima_bien_la_localia(self):
        rng = np.random.default_rng(2)
        m = fit_win_model(*mundo(rng, localia=2.2))
        assert m.margin_params["const"] == pytest.approx(2.2, abs=0.8)


class TestDosSenalesDeAcuerdo:
    """La regla de la casa: dos rutas independientes tienen que coincidir antes
    de publicar una probabilidad."""

    def test_las_dos_rutas_coinciden_en_un_mundo_normal(self):
        rng = np.random.default_rng(3)
        m = fit_win_model(*mundo(rng))
        for rd in (-10.0, -3.0, 0.0, 4.0, 12.0):
            f = GameFeatures(rd, True, 0.0, 0.0)
            assert m.agrees(f), f"discrepan con rating_diff={rd}"

    def test_la_probabilidad_publicada_esta_entre_las_dos(self):
        rng = np.random.default_rng(4)
        m = fit_win_model(*mundo(rng))
        f = GameFeatures(6.0, True, 1.0, 0.0)
        a, b = m.probability_logit(f), m.probability_margin(f)
        assert min(a, b) <= m.probability(f) <= max(a, b)


class TestCoherencia:
    def test_mas_rating_es_mas_probabilidad(self):
        rng = np.random.default_rng(5)
        m = fit_win_model(*mundo(rng))
        ps = [m.probability(GameFeatures(rd, True, 0.0, 0.0)) for rd in (-12, -4, 0, 4, 12)]
        assert ps == sorted(ps)

    def test_la_probabilidad_vive_en_el_intervalo_unidad(self):
        rng = np.random.default_rng(6)
        m = fit_win_model(*mundo(rng))
        for rd in (-100.0, 0.0, 100.0):
            assert 0.0 <= m.probability(GameFeatures(rd, True, 0.0, 0.0)) <= 1.0

    def test_el_descanso_ayuda(self):
        rng = np.random.default_rng(7)
        m = fit_win_model(*mundo(rng))
        base = GameFeatures(0.0, True, 0.0, 0.0)
        con = GameFeatures(0.0, True, 2.0, 0.0)
        assert m.probability(con) > m.probability(base)

    def test_la_regla_de_bolsillo_es_razonable(self):
        """Cerca del 50%, un punto porcentual son ~0,3 puntos de margen. Sirve
        para auditar a ojo cualquier salida del modelo."""
        rng = np.random.default_rng(8)
        m = fit_win_model(*mundo(rng))
        assert 0.2 < m.points_per_percent < 0.45


class TestCasosLimite:
    def test_muestra_insuficiente_no_devuelve_modelo(self):
        rng = np.random.default_rng(9)
        f, mg, y = mundo(rng, n=50)
        assert fit_win_model(f, mg, y) is None

    def test_sin_variacion_en_el_resultado_no_hay_nada_que_aprender(self):
        """Con todos los partidos ganados por el local, un modelo ajustado ahí
        daría 1,0 para todo."""
        f = [GameFeatures(float(i), True, 0.0, 0.0) for i in range(200)]
        assert fit_win_model(f, [10.0] * 200, [True] * 200) is None

    def test_una_columna_constante_no_rompe_el_ajuste(self):
        """En un backtest sin sedes neutrales, `home` vale 1 en todas las filas
        y colisiona con la constante."""
        rng = np.random.default_rng(10)
        m = fit_win_model(*mundo(rng))
        assert m is not None and m.margin_params["home"] == 0.0
