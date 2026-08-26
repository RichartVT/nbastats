"""El simulador y el informe de validación tienen que ser el MISMO modelo.

Este fichero existe por un fallo concreto. `build-ratings` ajustaba el modelo,
escribía las probabilidades y tiraba los coeficientes. El endpoint `/predict`,
sin nada de dónde leerlos, acabó con una fórmula propia y dos multiplicadores
escritos a mano (`* 0.35` para el descanso, `* 1.2` para el back-to-back), sin
intercepto y con la diferencia de rating entrando con coeficiente 1,0 implícito.

La pantalla enseñaba probabilidades que no eran las que se habían validado, y
nada fallaba. Estos tests hacen imposible que vuelva a pasar en silencio.
"""

from __future__ import annotations

import numpy as np
import pytest

from nbastats.analysis.forecast import (
    FEATURES,
    GameFeatures,
    fit_win_model,
    model_from_params,
)


def mundo(rng, n=3000):
    rd = rng.normal(0, 6, n)
    rest = rng.integers(-2, 3, n).astype(float)
    b2b = rng.integers(-1, 2, n).astype(float)
    margen = 1.05 * rd + 2.2 + 0.4 * rest + 1.2 * b2b + rng.normal(0, 13, n)
    feats = [
        GameFeatures(float(a), True, float(b), float(c))
        for a, b, c in zip(rd, rest, b2b, strict=True)
    ]
    return feats, margen, margen > 0


class TestRoundTrip:
    """Guardar y recuperar los coeficientes no puede cambiar ni una cifra."""

    def test_la_probabilidad_sobrevive_al_viaje(self):
        rng = np.random.default_rng(0)
        feats, margenes, ganó = mundo(rng)
        original = fit_win_model(feats, margenes, ganó)

        # Lo que haría la base: guardar los dicts y volver a montar el modelo.
        recuperado = model_from_params(
            original.logit_params, original.margin_params,
            original.sigma, original.n_train,
        )
        for f in feats[:200]:
            assert recuperado.probability(f) == pytest.approx(
                original.probability(f), abs=1e-12
            )

    def test_el_margen_esperado_tambien(self):
        rng = np.random.default_rng(1)
        feats, margenes, ganó = mundo(rng)
        o = fit_win_model(feats, margenes, ganó)
        r = model_from_params(o.logit_params, o.margin_params, o.sigma)
        for f in feats[:200]:
            assert r.expected_margin(f) == pytest.approx(o.expected_margin(f), abs=1e-12)

    def test_las_dos_rutas_por_separado(self):
        rng = np.random.default_rng(2)
        feats, margenes, ganó = mundo(rng)
        o = fit_win_model(feats, margenes, ganó)
        r = model_from_params(o.logit_params, o.margin_params, o.sigma)
        f = feats[0]
        assert r.probability_logit(f) == pytest.approx(o.probability_logit(f), abs=1e-12)
        assert r.probability_margin(f) == pytest.approx(o.probability_margin(f), abs=1e-12)


class TestCoeficientesCompletos:
    def test_se_guardan_todas_las_variables_y_la_constante(self):
        """Si faltara una, el modelo recuperado la trataría como cero y la
        pantalla diferiría del informe justo en esa variable."""
        rng = np.random.default_rng(3)
        o = fit_win_model(*mundo(rng))
        for nombre in ("const", *FEATURES):
            assert nombre in o.margin_params
            assert nombre in o.logit_params

    def test_una_variable_ausente_vale_cero_no_rompe(self):
        """`home` se descarta del ajuste cuando es constante. Recuperarlo debe
        dar 0.0, que es exactamente su efecto: ninguno."""
        m = model_from_params({"const": 0.2}, {"const": 2.0, "rating_diff": 1.0}, 13.0)
        assert m.margin_params["b2b_diff"] == 0.0
        assert m.margin_params["rating_diff"] == 1.0


class TestElDesgloseSumaElMargen:
    """La propiedad que hace auditable la pantalla: si las barras no suman el
    margen esperado, el desglose es decorativo."""

    def test_los_componentes_reproducen_el_margen(self):
        rng = np.random.default_rng(4)
        feats, margenes, ganó = mundo(rng)
        m = fit_win_model(feats, margenes, ganó)
        c = m.margin_params
        for f in feats[:100]:
            componentes = (
                c["rating_diff"] * f.rating_diff
                + c["const"]
                + c["rest_diff"] * f.rest_diff
                + c["b2b_diff"] * f.b2b_diff
            )
            assert componentes == pytest.approx(m.expected_margin(f), abs=1e-9)


class TestNoSeVuelvenAInventarCoeficientes:
    """Los literales que causaron el fallo: 0.35 para el descanso y 1.2 para el
    back-to-back. El ajuste real no tiene por qué parecerse a ellos, y ese es
    justo el problema de escribirlos a mano."""

    def test_el_coeficiente_ajustado_no_es_el_literal_viejo(self):
        rng = np.random.default_rng(5)
        m = fit_win_model(*mundo(rng))
        # El mundo sintético usa 0.4 y 1.2; el ajuste los recupera. Lo que se
        # comprueba aquí es que los coeficientes VIENEN del ajuste, no de una
        # constante: cambiando el mundo, cambian.
        rng2 = np.random.default_rng(6)
        rd = rng2.normal(0, 6, 3000)
        rest = rng2.integers(-2, 3, 3000).astype(float)
        b2b = rng2.integers(-1, 2, 3000).astype(float)
        margen2 = 1.05 * rd + 2.2 + 2.5 * rest + 4.0 * b2b + rng2.normal(0, 13, 3000)
        feats2 = [
            GameFeatures(float(a), True, float(b), float(c))
            for a, b, c in zip(rd, rest, b2b, strict=True)
        ]
        m2 = fit_win_model(feats2, margen2, margen2 > 0)
        assert m2.margin_params["rest_diff"] > 2.0
        assert m2.margin_params["rest_diff"] > m.margin_params["rest_diff"] * 2
