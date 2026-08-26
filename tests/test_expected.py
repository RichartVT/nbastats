"""Tests del motor de resultado esperado.

Lo que se prueba aquí es sobre todo UNA cosa: que el desglose **cierre**. Un
reparto de puntos que no suma el margen no es un desglose, es una lista de
opiniones — y el error se puede quedar años sin que nadie lo note, porque cada
cifra suelta parece razonable.
"""

from __future__ import annotations

import pytest

from nbastats.analysis.expected import (
    ShootingNorms,
    TeamBox,
    attribute_margin,
    exact_product_split,
    expected_points,
    four_factors,
    league_norms,
    shrunk_norm,
    team_luck,
)


def caja(**cambios) -> TeamBox:
    base = dict(
        pts=110, fgm=40, fga=88, fg3m=12, fg3a=35, ftm=18, fta=22,
        oreb=10, dreb=33, tov=13,
    )
    base.update(cambios)
    # Se respeta la identidad de puntos salvo que el test la fuerce.
    if "pts" not in cambios:
        base["pts"] = 2 * base["fgm"] + base["fg3m"] + base["ftm"]
    return TeamBox(**base)


NORMAS = ShootingNorms(fg2_pct=0.54, fg3_pct=0.36, ft_pct=0.78, n_games=70)


class TestCajaDeEquipo:
    def test_los_tiros_de_dos_son_los_de_campo_menos_los_triples(self):
        b = caja(fgm=40, fg3m=12, fga=88, fg3a=35)
        assert b.fg2m == 28 and b.fg2a == 53

    def test_efg_pondera_el_triple_una_vez_y_media(self):
        """Un 45% de triples y un 45% de dobles no valen lo mismo: el triple da
        1,5 veces los puntos."""
        b = caja(fgm=40, fg3m=12, fga=88)
        assert b.efg_pct == pytest.approx((40 + 6) / 88)

    def test_sin_tiros_no_hay_porcentaje(self):
        assert caja(fga=0, fgm=0, fg3a=0, fg3m=0).efg_pct is None


class TestDesgloseCierra:
    """La propiedad que sostiene todo el motor."""

    def test_los_componentes_suman_la_desviacion_del_equipo(self):
        b = caja()
        s = team_luck(b, NORMAS)
        assert sum(c.points for c in s.components) == pytest.approx(s.total, abs=1e-9)

    def test_el_desglose_del_partido_no_deja_residuo(self):
        a = attribute_margin(caja(), NORMAS, caja(fgm=36, fg3m=8, ftm=20), NORMAS)
        assert a.unexplained_pts == pytest.approx(0.0, abs=1e-9)

    def test_los_componentes_suman_exactamente_el_vuelco(self):
        a = attribute_margin(caja(), NORMAS, caja(fgm=36, fg3m=8, ftm=20), NORMAS)
        assert sum(c.points for c in a.components) == pytest.approx(a.swing, abs=1e-9)

    @pytest.mark.parametrize("fg3m", [0, 5, 12, 20, 35])
    def test_cierra_sea_cual_sea_el_acierto(self, fg3m):
        a = attribute_margin(caja(fg3m=fg3m), NORMAS, caja(), NORMAS)
        assert a.unexplained_pts == pytest.approx(0.0, abs=1e-9)

    def test_cierra_con_un_equipo_que_no_tiro_de_tres(self):
        a = attribute_margin(caja(fg3a=0, fg3m=0), NORMAS, caja(), NORMAS)
        assert a.unexplained_pts == pytest.approx(0.0, abs=1e-9)


class TestSignos:
    def test_acertar_por_encima_de_la_norma_da_puntos_positivos(self):
        s = team_luck(caja(fg3m=20, fg3a=35), NORMAS)
        triples = next(c for c in s.components if c.key == "triples")
        assert triples.points > 0

    def test_el_acierto_del_visitante_resta_al_local(self):
        """Convención obligada: todo se mide desde el local, o los sumandos de
        los dos equipos no se pueden sumar entre sí."""
        a = attribute_margin(caja(), NORMAS, caja(fg3m=25, fg3a=35), NORMAS)
        v = next(c for c in a.components if c.key == "visitante_triples")
        assert v.points < 0

    def test_cada_triple_de_mas_vale_exactamente_tres_puntos(self):
        """Con los intentos fijos. Es la cifra que cualquiera comprueba a mano."""
        base = team_luck(caja(fg3m=12), NORMAS)
        mas = team_luck(caja(fg3m=16), NORMAS)
        d = lambda s: next(c for c in s.components if c.key == "triples").points  # noqa: E731
        assert d(mas) - d(base) == pytest.approx(12.0)


class TestVuelco:
    def test_detecta_que_el_desglose_senalaba_al_otro(self):
        perdedor = caja(fgm=38, fg3m=10, ftm=16)
        ganador = caja(fgm=38, fg3m=20, ftm=16)  # gana metiendo muchos más triples
        a = attribute_margin(perdedor, NORMAS, ganador, NORMAS)
        assert a.actual_margin < 0
        assert a.flipped is (a.expected_margin > 0)

    def test_un_empate_no_es_un_vuelco(self):
        a = attribute_margin(caja(), NORMAS, caja(), NORMAS)
        assert a.flipped is False


class TestPuntosEsperados:
    def test_con_acierto_igual_a_la_norma_no_hay_desviacion(self):
        b = TeamBox(pts=0, fgm=0, fga=100, fg3m=0, fg3a=0, ftm=0, fta=0,
                    oreb=0, dreb=0, tov=0)
        # 100 tiros de 2 al 54% = 108 puntos
        assert expected_points(b, NORMAS) == pytest.approx(108.0)

    def test_sin_tiros_no_se_esperan_puntos(self):
        b = TeamBox(pts=0, fgm=0, fga=0, fg3m=0, fg3a=0, ftm=0, fta=0,
                    oreb=0, dreb=0, tov=0)
        assert expected_points(b, NORMAS) == 0.0


class TestReglaExactaDelProducto:
    @pytest.mark.parametrize(
        ("x", "xh", "y", "yh"),
        [(10, 8, 3, 2), (100, 100, 1.1, 1.0), (0, 5, 2, 2), (-3, 1, 4, -2)],
    )
    def test_reparte_sin_residuo(self, x, xh, y, yh):
        """Es una identidad algebraica, no una aproximación."""
        a, b = exact_product_split(x, xh, y, yh)
        assert a + b == pytest.approx(x * y - xh * yh)

    def test_si_un_factor_no_cambia_no_aporta(self):
        _, efecto_y = exact_product_split(10, 8, 3, 3)
        assert efecto_y == pytest.approx(0.0)


class TestNormaEncogida:
    def test_sin_intentos_devuelve_la_liga(self):
        assert shrunk_norm(0, 0, 0.36, 100) == 0.36

    def test_con_los_intentos_del_prior_pesa_la_mitad(self):
        """Es la definición del parámetro, y hace que se pueda leer en voz alta:
        'hacen falta 100 triples para que su porcentaje pese lo mismo que la
        liga'."""
        assert shrunk_norm(50, 100, 0.30, 100) == pytest.approx((0.5 + 0.3) / 2)

    def test_con_muchos_intentos_gana_el_dato_propio(self):
        assert shrunk_norm(4000, 10000, 0.30, 100) == pytest.approx(0.40, abs=0.01)


class TestNormaDeLiga:
    def test_se_agrega_sobre_totales_no_promediando_porcentajes(self):
        """Promediar razones pondera igual un partido de 40 triples y uno de 4,
        y da un número distinto y equivocado."""
        muchos = caja(fg3m=20, fg3a=40)
        pocos = caja(fg3m=0, fg3a=4)
        n = league_norms([muchos, pocos])
        assert n.fg3_pct == pytest.approx(20 / 44)
        assert n.fg3_pct != pytest.approx((20 / 40 + 0 / 4) / 2)

    def test_cuenta_los_partidos(self):
        assert league_norms([caja(), caja(), caja()]).n_games == 3


class TestFourFactors:
    def test_el_rebote_ofensivo_necesita_al_rival(self):
        """OREB% es sobre los rebotes DISPONIBLES, no sobre los propios."""
        ff = four_factors(caja(oreb=10), caja(dreb=30))
        assert ff.oreb_pct == pytest.approx(10 / 40)

    def test_usa_la_formula_de_posesiones_no_el_dato_de_la_api(self):
        """Solo con la fórmula cierra la identidad de los cuatro factores."""
        b = caja(fga=88, oreb=10, tov=13, fta=22)
        assert four_factors(b, caja()).possessions == pytest.approx(88 - 10 + 13 + 0.44 * 22)

    def test_sin_tiros_no_hay_factores(self):
        vacio = TeamBox(pts=0, fgm=0, fga=0, fg3m=0, fg3a=0, ftm=0, fta=0,
                        oreb=0, dreb=0, tov=0)
        ff = four_factors(vacio, vacio)
        assert ff.efg_pct is None and ff.ft_rate is None
