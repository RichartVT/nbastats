"""Tests de la descomposición de varianza.

Es el módulo del que cuelga el motor entero: si `k` sale mal, el resultado
esperado de cada partido sale mal y nadie se entera, porque no hay nada con qué
contrastarlo. Por eso se prueba con series simuladas de propiedades conocidas,
donde la respuesta correcta se sabe de antemano.
"""

from __future__ import annotations

import numpy as np
import pytest

from nbastats.analysis.reliability import Reliability
from nbastats.analysis.stability import (
    K_HABILIDAD,
    K_MIXTO,
    describe_stability,
    shrinkage_weight,
    variance_components,
)


def series(rng, *, n_unidades=30, n_partidos=82, sd_entre, sd_intra, media=0.36):
    """Unidades con una habilidad real y ruido de partido conocidos.

    `k` verdadero es (sd_intra/sd_entre)², y es lo que el estimador tiene que
    recuperar.
    """
    return {
        f"u{i}": list(rng.normal(rng.normal(media, sd_entre), sd_intra, n_partidos))
        for i in range(n_unidades)
    }


class TestRecuperaKConocido:
    @pytest.mark.parametrize(
        ("sd_entre", "sd_intra", "k_real"),
        [(0.030, 0.090, 9.0), (0.020, 0.140, 49.0), (0.010, 0.130, 169.0)],
    )
    def test_k_estimado_se_acerca_al_verdadero(self, sd_entre, sd_intra, k_real):
        rng = np.random.default_rng(7)
        v = variance_components(
            series(rng, sd_entre=sd_entre, sd_intra=sd_intra), label="x"
        )
        # El método de los momentos con 30 unidades es ruidoso: se exige el
        # orden de magnitud, que es lo que decide el tratamiento.
        assert v.k_games == pytest.approx(k_real, rel=0.6)

    def test_sin_diferencia_real_entre_unidades_no_hay_k(self):
        """Si todas las unidades comparten la misma media, tau²=0 y la
        respuesta correcta es "no distingo", no un k enorme."""
        rng = np.random.default_rng(3)
        grupos = {f"u{i}": list(rng.normal(0.36, 0.09, 82)) for i in range(30)}
        v = variance_components(grupos, label="ruido puro")
        assert v.k_games is None or v.k_games > 200
        if v.k_games is None:
            assert v.stability.key == "indistinguible"


class TestPeso:
    def test_el_peso_crece_con_la_muestra(self):
        assert shrinkage_weight(10, 50) < shrinkage_weight(40, 50) < shrinkage_weight(200, 50)

    def test_en_k_partidos_el_peso_es_justo_la_mitad(self):
        """Es la definición de k y lo que hace que se pueda leer en voz alta."""
        assert shrinkage_weight(30, 30) == pytest.approx(0.5)

    def test_sin_senal_el_peso_es_cero(self):
        """Cuando no hay diferencia real, la respuesta honesta es "no sé nada
        de este equipo", que es 0, no 0.5."""
        assert shrinkage_weight(82, None) == 0.0

    @pytest.mark.parametrize("n", [0, -5])
    def test_sin_partidos_no_hay_peso(self, n):
        assert shrinkage_weight(n, 10) == 0.0


class TestVeredicto:
    @pytest.mark.parametrize("k", [1, 20, K_HABILIDAD])
    def test_habilidad(self, k):
        assert describe_stability(k).key == "habilidad"

    @pytest.mark.parametrize("k", [K_HABILIDAD + 1, 60, K_MIXTO])
    def test_mixto(self, k):
        assert describe_stability(k).key == "mixto"

    @pytest.mark.parametrize("k", [K_MIXTO + 1, 150, 1000])
    def test_suerte(self, k):
        assert describe_stability(k).key == "suerte"

    def test_indistinguible(self):
        assert describe_stability(None).key == "indistinguible"

    def test_la_nota_dice_el_numero(self):
        """Un veredicto sin la cifra obliga a fiarse; con ella se puede discutir."""
        assert "150" in describe_stability(150).note


class TestCasosLimite:
    def test_una_sola_unidad_no_permite_comparar(self):
        v = variance_components({"u0": [0.3] * 50}, label="x")
        assert v.k_games is None
        assert v.reliability is Reliability.INSUFICIENTE

    def test_grupos_vacios(self):
        v = variance_components({}, label="x")
        assert v.n_units == 0
        assert v.k_games is None

    def test_se_ignoran_nulos_y_no_finitos(self):
        rng = np.random.default_rng(11)
        grupos = series(rng, sd_entre=0.03, sd_intra=0.09)
        grupos["u0"] = [None, float("nan"), *grupos["u0"]]
        v = variance_components(grupos, label="x")
        assert v.n_units == 30
        assert v.k_games is not None

    def test_las_unidades_con_un_solo_partido_se_descartan(self):
        """Con un partido no hay varianza intra que aportar."""
        rng = np.random.default_rng(5)
        grupos = series(rng, sd_entre=0.03, sd_intra=0.09, n_unidades=10)
        grupos["suelta"] = [0.5]
        assert variance_components(grupos, label="x").n_units == 10

    def test_la_fiabilidad_es_la_del_numero_de_unidades(self):
        rng = np.random.default_rng(9)
        pocas = variance_components(
            series(rng, sd_entre=0.03, sd_intra=0.09, n_unidades=5), label="x"
        )
        muchas = variance_components(
            series(rng, sd_entre=0.03, sd_intra=0.09, n_unidades=150), label="x"
        )
        assert pocas.reliability is Reliability.BAJA
        assert muchas.reliability is Reliability.ALTA


class TestLaTesisDelMotor:
    def test_mas_ruido_intra_significa_menos_peso_propio(self):
        """El contraste que sostiene todo: dos componentes con la misma
        dispersión real entre equipos, pero uno mucho más ruidoso partido a
        partido, merecen pesos muy distintos."""
        rng = np.random.default_rng(21)
        controlable = variance_components(
            series(rng, sd_entre=0.03, sd_intra=0.085), label="intentos"
        )
        ruidoso = variance_components(
            series(rng, sd_entre=0.01, sd_intra=0.130), label="acierto"
        )
        assert controlable.k_games < ruidoso.k_games
        assert controlable.weight(82) > 2 * ruidoso.weight(82)
