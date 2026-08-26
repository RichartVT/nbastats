"""Los endpoints que exponen `expected` y `stability`.

No tocan la base: prueban la aritmética de la capa de composición, que es donde
un endpoint puede traicionar en silencio al módulo puro que dice usar.
"""

from __future__ import annotations

import pytest

from nbastats.analysis.expected import (
    ShootingNorms,
    TeamBox,
    attribute_margin,
    shrunk_norm,
)
from nbastats.api.main import _COMPONENTES, _PRIOR_INTENTOS, _valor

FILA = {
    "fga": 80, "fgm": 40, "fg3a": 30, "fg3m": 12, "fta": 20, "ftm": 16,
    "oreb": 10, "dreb": 35, "tov": 15, "pace": 99.5,
    "pts_paint": 44, "pts_fastbreak": 12, "pts_off_turnovers": 18, "pts_2nd_chance": 10,
    "opp_fga": 85, "opp_fgm": 38, "opp_fg3a": 40, "opp_fg3m": 15, "opp_dreb": 30,
}


def test_efg_pondera_el_triple_una_vez_y_media():
    """Un 45% de triples y un 45% de dobles no valen lo mismo."""
    assert _valor(FILA, "efg_pct") == pytest.approx((40 + 0.5 * 12) / 80)


def test_las_posesiones_usan_la_formula_y_no_el_dato_de_la_api():
    """`FGA − OREB + TOV + 0,44·FTA`. Solo con la fórmula cierra la identidad."""
    poss = 80 - 10 + 15 + 0.44 * 20
    assert _valor(FILA, "tov_rate") == pytest.approx(15 / poss)


def test_el_rebote_ofensivo_se_mide_contra_los_disponibles():
    """No contra los propios: el denominador es lo que hubo que disputar."""
    assert _valor(FILA, "oreb_pct") == pytest.approx(10 / (10 + 30))


def test_lo_concedido_sale_de_la_fila_del_rival():
    """Separa el VOLUMEN concedido del ACIERTO concedido, que es el par entero
    sobre el que se apoya el motor de resultado esperado."""
    assert _valor(FILA, "opp_fg3_pct") == pytest.approx(15 / 40)
    assert _valor(FILA, "opp_fg3a") == 40


def test_una_division_por_cero_devuelve_none_y_no_revienta():
    vacio = dict.fromkeys(FILA, 0)
    for clave in _COMPONENTES:
        assert _valor(vacio, clave) in (None, 0.0)


def test_todos_los_componentes_del_catalogo_se_saben_calcular():
    """Si alguien añade una clave a `_COMPONENTES` y olvida `_valor`, la tabla
    la omitiría en silencio en vez de fallar."""
    for clave in _COMPONENTES:
        assert _valor(FILA, clave) is not None, clave


def test_el_prior_del_triple_es_mayor_que_el_del_doble():
    """El acierto de 3 es mucho más ruidoso (k=150 contra k=16), así que su
    media propia necesita más intentos para ganarse el mismo peso."""
    assert _PRIOR_INTENTOS["fg3"] > _PRIOR_INTENTOS["fg2"] > _PRIOR_INTENTOS["ft"]


def test_sin_intentos_la_norma_es_la_de_la_liga():
    assert shrunk_norm(0, 0, 0.36, 1400.0) == pytest.approx(0.36)


def test_el_desglose_cierra_con_normas_encogidas():
    """La condición que el endpoint promete: la suma de componentes ES la
    diferencia entre margen real y esperado, también con normas por equipo."""
    local = TeamBox(118, 44, 90, 14, 38, 16, 20, 11, 33, 13)
    visitante = TeamBox(112, 42, 88, 11, 34, 17, 22, 9, 35, 15)
    n_local = ShootingNorms(0.552, 0.371, 0.792, 81)
    n_vis = ShootingNorms(0.541, 0.352, 0.771, 81)

    atr = attribute_margin(local, n_local, visitante, n_vis)
    assert atr.unexplained_pts == pytest.approx(0.0, abs=1e-9)
    assert sum(c.points for c in atr.components) == pytest.approx(atr.swing, abs=1e-9)


def test_la_familia_de_cada_componente_es_conocida():
    assert {f for _, f in _COMPONENTES.values()} <= {
        "volumen", "acierto", "control", "origen"
    }
