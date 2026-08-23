"""Tests de la detección de tendencias."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from nbastats.analysis.reliability import Reliability
from nbastats.analysis.trends import (
    GAMES_PER_SEASON,
    AgeCurve,
    TrendDirection,
    age_adjusted_residuals,
    analyze_trend,
    detect_change_points,
    fit_age_curve,
    rolling_mean,
)


class TestRollingMean:
    def test_no_rellena_las_primeras_posiciones(self):
        # Un punto calculado con 3 partidos y otro con 25 no son comparables.
        out = rolling_mean([1.0] * 10, window=5)
        assert out[:4] == [None] * 4
        assert out[4:] == pytest.approx([1.0] * 6)

    def test_media_correcta(self):
        out = rolling_mean([1.0, 2.0, 3.0, 4.0, 5.0], window=3)
        assert out[2:] == pytest.approx([2.0, 3.0, 4.0])

    def test_serie_mas_corta_que_la_ventana(self):
        assert rolling_mean([1.0, 2.0], window=5) == [None, None]

    def test_ventana_invalida(self):
        with pytest.raises(ValueError):
            rolling_mean([1.0], window=0)


class TestAnalyzeTrend:
    def test_pocos_partidos_es_indeterminado(self):
        res = analyze_trend([20.0] * 10)
        assert res.direction is TrendDirection.INDETERMINADA
        assert not res.is_significant
        assert "hacen falta" in res.note

    def test_declive_real_se_detecta(self):
        rng = np.random.default_rng(0)
        # Cae 6 puntos a lo largo de 200 partidos, con ruido realista.
        serie = np.linspace(24.0, 18.0, 200) + rng.normal(0, 2.0, 200)

        res = analyze_trend(serie.tolist())
        assert res.direction is TrendDirection.DECLIVE
        assert res.slope_per_season < 0
        assert res.slope_ci95[1] < 0  # el IC excluye el cero
        assert res.tau < 0
        assert "baja" in res.note

    def test_alza_real_se_detecta(self):
        rng = np.random.default_rng(1)
        serie = np.linspace(12.0, 20.0, 200) + rng.normal(0, 2.0, 200)

        res = analyze_trend(serie.tolist())
        assert res.direction is TrendDirection.ALZA
        assert res.slope_per_season > 0
        assert res.slope_ci95[0] > 0

    def test_ruido_puro_no_produce_tendencia(self):
        """Sin señal no debe salir señal."""
        falsos = 0
        for semilla in range(60):
            rng = np.random.default_rng(semilla)
            serie = rng.normal(20.0, 5.0, 150).tolist()
            if analyze_trend(serie, find_change_points=False).is_significant:
                falsos += 1
        # Con α=0,05 y dos tests que deben coincidir, se espera bastante menos
        # del 5%. Se admite margen para no hacer el test frágil.
        assert falsos <= 5, f"{falsos}/60 falsos positivos: demasiados"

    def test_pendiente_por_temporada_es_coherente(self):
        serie = np.linspace(20.0, 10.0, 82).tolist()  # -10 en exactamente 82
        res = analyze_trend(serie)
        assert res.slope_per_season == pytest.approx(-10.0, abs=0.5)
        assert res.slope_per_game * GAMES_PER_SEASON == pytest.approx(
            res.slope_per_season
        )

    def test_serie_constante(self):
        res = analyze_trend([20.0] * 100)
        assert res.direction is TrendDirection.INDETERMINADA
        assert "variación" in res.note

    def test_ignora_none_y_nan(self):
        serie = [20.0, None, 21.0, float("nan"), 19.0] * 20
        res = analyze_trend(serie)
        assert res.n == 60  # 3 valores válidos por bloque × 20

    def test_reliability_se_propaga(self):
        rng = np.random.default_rng(4)
        corta = analyze_trend(rng.normal(20, 5, 25).tolist())
        larga = analyze_trend(rng.normal(20, 5, 300).tolist())
        assert corta.reliability is Reliability.MEDIA
        assert larga.reliability is Reliability.ALTA


class TestAutocorrelacion:
    """Por qué la regresión NO corre sobre la media móvil.

    Suavizar y luego regresar es un error habitual: los puntos consecutivos de
    una media móvil comparten observaciones y están autocorrelacionados, lo que
    hunde artificialmente el p-valor. Este test cuantifica el daño.
    """

    def test_suavizar_antes_de_regresar_fabrica_significancia(self):
        crudos_significativos = 0
        suavizados_significativos = 0

        for semilla in range(60):
            rng = np.random.default_rng(semilla)
            ruido = rng.normal(20.0, 5.0, 150)

            if analyze_trend(ruido.tolist(), find_change_points=False).is_significant:
                crudos_significativos += 1

            suave = [v for v in rolling_mean(ruido.tolist(), window=25) if v is not None]
            p = stats.linregress(np.arange(len(suave)), suave).pvalue
            if p < 0.05:
                suavizados_significativos += 1

        # Los mismos datos sin señal: la vía suavizada inventa tendencias.
        assert suavizados_significativos > crudos_significativos * 3, (
            f"crudos={crudos_significativos}, suavizados={suavizados_significativos}"
        )


class TestChangePoints:
    def test_detecta_un_escalon(self):
        rng = np.random.default_rng(2)
        serie = np.concatenate([
            rng.normal(22.0, 1.5, 60),   # nivel alto
            rng.normal(14.0, 1.5, 60),   # se desploma (lesión, cambio de rol)
        ])

        puntos = detect_change_points(serie.tolist())
        assert len(puntos) >= 1
        assert any(abs(p - 60) <= 10 for p in puntos), f"puntos hallados: {puntos}"

    def test_serie_estable_no_tiene_escalones(self):
        rng = np.random.default_rng(3)
        assert detect_change_points(rng.normal(20.0, 1.0, 200).tolist()) == []

    def test_serie_corta(self):
        assert detect_change_points([20.0] * 5) == []

    def test_serie_constante(self):
        assert detect_change_points([20.0] * 100) == []

    def test_el_aviso_aparece_en_la_nota(self):
        rng = np.random.default_rng(5)
        serie = np.concatenate([
            rng.normal(24.0, 1.0, 70),
            rng.normal(15.0, 1.0, 70),
        ])
        res = analyze_trend(serie.tolist())
        # Una recta describe mal un escalón: hay que avisarlo.
        assert "cambio(s) de nivel" in res.note


class TestAgeCurve:
    def test_ajusta_una_parabola_con_pico(self):
        rng = np.random.default_rng(6)
        edades = rng.uniform(20, 38, 400)
        # Pico real en 27.
        valores = 25 - 0.09 * (edades - 27) ** 2 + rng.normal(0, 1.0, 400)

        curva = fit_age_curve(edades.tolist(), valores.tolist())
        assert curva is not None
        assert curva.peak_age == pytest.approx(27.0, abs=1.0)
        assert curva.relative_to_peak(27.0) == pytest.approx(1.0, abs=0.02)
        assert curva.relative_to_peak(36.0) < 0.9

    def test_rechaza_muestra_insuficiente(self):
        assert fit_age_curve([25.0] * 10, [20.0] * 10) is None

    def test_rechaza_parabola_hacia_arriba(self):
        # Rango de edades estrecho: no se puede recuperar la forma.
        edades = np.linspace(24, 26, 100)
        valores = edades**2
        assert fit_age_curve(edades.tolist(), valores.tolist()) is None

    def test_residuos_separan_declive_normal_de_anomalo(self):
        curva = AgeCurve(a=-0.1, b=5.4, c=-48.0, peak_age=27.0, n_observations=500)

        edades = [30.0, 31.0, 32.0]
        # Un jugador que sigue exactamente la curva no está en declive anómalo.
        normales = [curva.expected(e) for e in edades]
        assert age_adjusted_residuals(edades, normales, curva) == pytest.approx(
            [0.0, 0.0, 0.0], abs=1e-9
        )

        # Uno que cae por debajo de lo esperado, sí.
        anomalos = [v - 3.0 for v in normales]
        assert all(r < -2.0 for r in age_adjusted_residuals(edades, anomalos, curva))
