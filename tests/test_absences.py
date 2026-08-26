"""El índice de ausencias: que describa bien, y que no se cuele en el pronóstico."""

from __future__ import annotations

import pytest

from nbastats.analysis.absences import (
    MINUTOS_ROTACION,
    PUNTOS_POR_MINUTO,
    describe_absences,
    margin_adjustment,
)


@pytest.mark.parametrize(
    ("minutos", "nivel"),
    [(0, "completa"), (19.9, "completa"), (20, "leve"), (59.9, "leve"),
     (60, "notable"), (99.9, "notable"), (100, "grave"), (250, "grave")],
)
def test_los_cortes_son_los_medidos(minutos, nivel):
    assert describe_absences(minutos, 1).level == nivel


def test_ninguno_es_none_ni_se_sale_de_los_niveles():
    """Cualquier valor tiene que caer en un nivel: no hay 'sin clasificar'."""
    for m in range(0, 400, 7):
        idx = describe_absences(m, 0)
        assert idx.level in ("completa", "leve", "notable", "grave")
        assert idx.label


def test_none_es_cero_y_no_desconocido():
    """La derivación cubre los 13.204 equipo-partido, así que un hueco sería un
    fallo de la derivación, no falta de información."""
    assert describe_absences(None, None).minutes == 0.0
    assert describe_absences(None, None).level == "completa"


def test_el_coste_es_monotono_y_siempre_en_contra():
    """Más ausencias nunca pueden ayudar."""
    costes = [describe_absences(m, 1).margin_cost for m in (0, 30, 70, 120, 200)]
    assert costes == sorted(costes, reverse=True)
    assert all(c <= 0 for c in costes)


def test_el_ajuste_es_antisimetrico():
    """Lo que le quita a uno se lo da al otro: si no, el margen no cerraría."""
    assert margin_adjustment(80, 20) == pytest.approx(-margin_adjustment(20, 80))
    assert margin_adjustment(40, 40) == 0.0


def test_cien_minutos_valen_lo_medido():
    """3,7 puntos por cada 100 minutos fuera. Si esto cambia sin volver a medir,
    alguien tocó una constante que salió de una regresión."""
    assert margin_adjustment(0, 100) == pytest.approx(3.73, abs=0.01)
    assert abs(PUNTOS_POR_MINUTO - 0.0373) < 1e-9


def test_el_indice_no_entra_en_las_variables_del_pronostico():
    """EL TEST QUE PROTEGE LA HONESTIDAD DE LAS MÉTRICAS.

    `GameFeatures` es lo que ve el modelo de probabilidad. Si algún día alguien
    añade ahí las ausencias, el backtest subirá y dejará de significar nada: que
    un jugador no aparezca en el box score se sabe DESPUÉS del partido.
    """
    from nbastats.analysis.forecast import FEATURES, GameFeatures

    campos = set(GameFeatures.__dataclass_fields__)
    prohibidos = {"absent", "absences", "ausencias", "absent_minutes"}
    assert not (campos & prohibidos)
    assert not any("absent" in f or "ausen" in f for f in FEATURES)


def test_el_umbral_de_rotacion_es_el_convencional():
    assert MINUTOS_ROTACION == 10.0
