"""Tests de la calibración.

Se prueba sobre datos SIMULADOS de calibración conocida, que es la única forma
de saber si el diagnóstico funciona: con datos reales no hay verdad contra la
que comparar. Y se prueba lo que puede fallar en silencio — que un modelo
sobreconfiado se detecte, y que el suelo de ruido no se olvide.
"""

from __future__ import annotations

import numpy as np
import pytest

from nbastats.analysis.calibration import (
    brier,
    brier_skill_score,
    calibration_bins,
    calibration_report,
    ece_noise_floor,
    expected_calibration_error,
    log_loss,
    wilson_interval,
)


def mundo(rng, n=5000, distorsion=1.0):
    """Predicciones y resultados con calibración conocida.

    `distorsion=1` es calibración perfecta; >1 estira hacia los extremos
    (exceso de confianza); <1 encoge hacia 0,5 (exceso de prudencia).
    """
    p = rng.uniform(0.15, 0.9, n)
    y = rng.random(n) < p
    logit = np.log(p / (1 - p)) * distorsion
    return 1 / (1 + np.exp(-logit)), y


class TestMetricas:
    def test_brier_de_prediccion_perfecta_es_cero(self):
        assert brier([1.0, 0.0, 1.0], [1, 0, 1]) == 0.0

    def test_brier_castiga_la_confianza_mal_puesta(self):
        """Es la diferencia con la precisión: fallar diciendo 0,95 duele mucho
        más que fallar diciendo 0,55."""
        assert brier([0.95], [0]) > brier([0.55], [0])

    def test_log_loss_no_estalla_con_certeza_absoluta(self):
        """Sin recorte, un 0 o un 1 exactos dan infinito y un solo partido
        arruinaría la métrica de todos."""
        assert np.isfinite(log_loss([1.0, 0.0], [0, 1]))

    def test_bss_cero_cuando_no_se_mejora_la_linea_base(self):
        y = [1, 0, 1, 0]
        assert brier_skill_score([0.5] * 4, y, 0.5) == pytest.approx(0.0)

    def test_bss_negativo_si_es_peor_que_no_hacer_nada(self):
        """Tiene que poder salir negativo: es un resultado posible y hay que
        poder publicarlo."""
        assert brier_skill_score([0.9, 0.9, 0.9, 0.9], [0, 0, 0, 1], 0.25) < 0

    def test_tamanos_distintos_es_error(self):
        with pytest.raises(ValueError, match="mismo tamaño"):
            brier([0.5, 0.5], [1])


class TestWilson:
    def test_centrado_en_la_proporcion(self):
        lo, hi = wilson_interval(50, 100)
        assert lo < 0.5 < hi

    def test_no_se_sale_del_intervalo_unidad(self):
        """Es el motivo de usar Wilson y no el intervalo normal: con 0 de 10, el
        normal da un límite inferior negativo."""
        lo, hi = wilson_interval(0, 10)
        assert lo >= 0.0 and hi <= 1.0

    def test_mas_muestra_estrecha_el_intervalo(self):
        anch = lambda s, n: (lambda t: t[1] - t[0])(wilson_interval(s, n))  # noqa: E731
        assert anch(500, 1000) < anch(50, 100)

    def test_sin_muestra_no_se_sabe_nada(self):
        assert wilson_interval(0, 0) == (0.0, 1.0)


class TestSueloDeRuido:
    def test_el_ece_perfecto_no_es_cero(self):
        """Con tramos finitos, la frecuencia observada se desvía de la predicha
        por puro muestreo. Publicar el ECE sin el suelo invita a leer ruido
        como sesgo."""
        assert ece_noise_floor(400) > 0

    def test_baja_con_mas_muestra_por_tramo(self):
        assert ece_noise_floor(4000) < ece_noise_floor(400)

    def test_sin_muestra_es_cero(self):
        assert ece_noise_floor(0) == 0.0


class TestDiagnostico:
    def test_un_modelo_calibrado_sale_calibrado(self):
        rng = np.random.default_rng(0)
        p, y = mundo(rng)
        r = calibration_report(p, y)
        assert r.within_noise
        assert r.slope == pytest.approx(1.0, abs=0.15)
        assert all(b.calibrated for b in r.bins)

    def test_el_exceso_de_confianza_se_delata_en_la_pendiente(self):
        """Pendiente < 1 significa que el modelo separa más de lo que debería.
        Es el diagnóstico que diez tramos no dan con precisión, porque cada uno
        tiene demasiado poco n."""
        rng = np.random.default_rng(1)
        p, y = mundo(rng, distorsion=1.8)
        r = calibration_report(p, y)
        assert r.slope < 0.8
        assert not r.within_noise

    def test_el_exceso_de_prudencia_tambien(self):
        rng = np.random.default_rng(2)
        p, y = mundo(rng, distorsion=0.5)
        assert calibration_report(p, y).slope > 1.3

    def test_la_nota_avisa_de_cuanto_se_puede_detectar(self):
        rng = np.random.default_rng(3)
        p, y = mundo(rng, n=500)
        assert "tramo" in calibration_report(p, y).note


class TestTramos:
    def test_los_tramos_vacios_no_aparecen(self):
        """Un modelo que nunca pasa de 0,85 debe enseñarlo, no rellenar con
        ceros los tramos altos."""
        p = [0.3] * 100
        b = calibration_bins(p, [1] * 50 + [0] * 50)
        assert len(b) == 1 and b[0].low == pytest.approx(0.3, abs=0.1)

    def test_el_ultimo_tramo_incluye_el_uno(self):
        assert sum(b.n for b in calibration_bins([1.0], [1])) == 1

    def test_todas_las_predicciones_caen_en_algun_tramo(self):
        rng = np.random.default_rng(4)
        p, y = mundo(rng, n=1000)
        assert sum(b.n for b in calibration_bins(p, y)) == 1000

    def test_el_ece_pondera_por_el_tamano_del_tramo(self):
        """Un tramo con 10 predicciones no puede pesar lo mismo que uno con 800."""
        b = calibration_bins([0.1] * 5 + [0.6] * 500, [1] * 5 + [1] * 300 + [0] * 200)
        assert expected_calibration_error(b) < 0.5

    def test_sin_datos_no_hay_informe(self):
        r = calibration_report([], [])
        assert r.bins == [] and "Sin predicciones" in r.note
