"""Tests de la capa de honestidad estadística.

El test que más importa es `test_efecto_sabado_inventado_no_se_detecta`: es
exactamente el escenario que motivó este módulo.
"""

from __future__ import annotations

import numpy as np
import pytest

from nbastats.analysis.reliability import (
    Reliability,
    analyze_splits,
    benjamini_hochberg,
    reliability_for,
)

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def temporada_sin_efecto(rng, *, media=22.0, sd=6.0, por_dia=12):
    """Un jugador cuyo rendimiento NO depende del día de la semana."""
    return {dia: rng.normal(media, sd, por_dia).tolist() for dia in DIAS}


class TestReliabilityTiers:
    @pytest.mark.parametrize(
        ("n", "esperado"),
        [
            (0, Reliability.INSUFICIENTE),
            (1, Reliability.INSUFICIENTE),
            (5, Reliability.BAJA),
            (14, Reliability.BAJA),
            (15, Reliability.MEDIA),
            (39, Reliability.MEDIA),
            (40, Reliability.ALTA),
            (200, Reliability.ALTA),
        ],
    )
    def test_umbrales(self, n, esperado):
        assert reliability_for(n) is esperado


class TestBenjaminiHochberg:
    def test_lista_vacia(self):
        assert benjamini_hochberg([]) == []

    def test_q_nunca_menor_que_p(self):
        p = [0.001, 0.01, 0.02, 0.03, 0.5, 0.9]
        q = benjamini_hochberg(p)
        assert all(qi >= pi - 1e-12 for pi, qi in zip(p, q, strict=True))

    def test_q_acotado_en_uno(self):
        assert all(qi <= 1.0 for qi in benjamini_hochberg([0.9, 0.95, 0.99]))

    def test_monotono_en_el_orden_de_p(self):
        p = [0.04, 0.001, 0.3, 0.02]
        q = np.array(benjamini_hochberg(p))
        orden = np.argsort(p)
        assert np.all(np.diff(q[orden]) >= -1e-12)

    def test_penaliza_comparaciones_multiples(self):
        # El mismo p=0.03 sobrevive solo si se probó poco.
        assert benjamini_hochberg([0.03])[0] == pytest.approx(0.03)
        muchos = benjamini_hochberg([0.03] + [0.6] * 99)
        assert muchos[0] > 0.05  # ya no es "significativo"


class TestShrinkage:
    def test_muestra_grande_respeta_la_media_del_split(self):
        rng = np.random.default_rng(0)
        grupos = {
            "sáb": rng.normal(30.0, 5.0, 400).tolist(),
            "otros": rng.normal(20.0, 5.0, 400).tolist(),
        }
        est = analyze_splits(grupos)["sáb"]
        # Con n grande y efecto real, apenas se encoge.
        assert est.shrunk_mean == pytest.approx(est.raw_mean, abs=0.5)
        assert est.reliability is Reliability.ALTA

    def test_muestra_minima_se_encoge_hacia_el_promedio_general(self):
        rng = np.random.default_rng(1)
        base = rng.normal(20.0, 6.0, 300).tolist()
        grupos = {"raro": [45.0], "resto": base}

        est = analyze_splits(grupos)["raro"]
        # La media cruda es 45 pero no hay evidencia; se reporta cerca de 20.
        assert est.raw_mean == 45.0
        assert abs(est.shrunk_mean - 20.0) < abs(est.raw_mean - 20.0)
        assert est.reliability is Reliability.INSUFICIENTE
        assert not est.distinguishable

    def test_display_mean_usa_la_encogida_si_no_es_distinguible(self):
        rng = np.random.default_rng(2)
        grupos = temporada_sin_efecto(rng)
        for est in analyze_splits(grupos).values():
            if not est.distinguishable:
                assert est.display_mean == est.shrunk_mean


class TestEscenarioSabado:
    def test_efecto_sabado_inventado_no_se_detecta(self):
        """Cinco temporadas sin efecto real: no debe salir ningún patrón.

        Este es el caso que el sistema tiene que manejar bien. Los datos se
        generan de una única distribución — no hay efecto de día de ninguna
        clase. Si el análisis reporta un "patrón de sábado" aquí, está
        fabricando señal.
        """
        fallos = 0
        for semilla in range(40):
            rng = np.random.default_rng(semilla)
            grupos = temporada_sin_efecto(rng, por_dia=60)  # ~5 temporadas
            resultados = analyze_splits(grupos)
            fallos += sum(1 for e in resultados.values() if e.distinguishable)

        # 40 simulaciones × 7 días = 280 comparaciones. Con control de FDR al
        # 5% se admite algún falso positivo aislado, no una cosecha de ellos.
        assert fallos <= 14, f"{fallos} falsos positivos de 280: demasiados"

    def test_una_temporada_de_sabados_avisa_de_muestra_pequena(self):
        rng = np.random.default_rng(7)
        grupos = temporada_sin_efecto(rng, por_dia=12)  # 1 temporada
        est = analyze_splits(grupos)["sáb"]

        assert est.n == 12
        assert est.reliability is Reliability.BAJA
        assert not est.distinguishable
        # El margen de error debe ser lo bastante ancho como para dejar claro
        # que no se puede concluir nada.
        margen = est.ci95_high - est.raw_mean
        assert margen > 2.0
        assert "margen de error" in est.note

    def test_efecto_real_y_grande_si_se_detecta(self):
        """Contraprueba: el sistema no es ciego, solo prudente."""
        rng = np.random.default_rng(3)
        grupos = {dia: rng.normal(20.0, 5.0, 60).tolist() for dia in DIAS}
        grupos["sáb"] = rng.normal(32.0, 5.0, 60).tolist()  # +12 puntos, real

        est = analyze_splits(grupos)["sáb"]
        assert est.distinguishable
        assert est.q_value < 0.05
        assert est.diff_vs_baseline > 8
        assert "se sostiene" in est.note


class TestCasosLimite:
    def test_grupos_vacios(self):
        res = analyze_splits({"a": [], "b": []})
        assert all(e.n == 0 for e in res.values())
        assert all(e.reliability is Reliability.INSUFICIENTE for e in res.values())
        assert all("Sin partidos" in e.note for e in res.values())

    def test_un_solo_grupo(self):
        est = analyze_splits({"todos": [10.0, 20.0, 30.0]})["todos"]
        assert est.n == 3
        assert not est.distinguishable  # no hay con qué comparar

    def test_mezcla_de_grupos_vacios_y_llenos(self):
        res = analyze_splits({"lleno": [10.0] * 20, "vacio": []})
        assert res["lleno"].n == 20
        assert res["vacio"].n == 0

    def test_conserva_todas_las_etiquetas(self):
        grupos = temporada_sin_efecto(np.random.default_rng(9))
        assert set(analyze_splits(grupos)) == set(DIAS)
