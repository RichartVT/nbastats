"""El corte de temporada: qué carga `daily` cada día.

POR QUÉ IMPORTA MÁS DE LO QUE PARECE. `daily` no recibe la temporada, la
calcula. Si el corte de octubre se equivoca, la actualización diaria recarga la
temporada equivocada durante semanas sin dar un solo error: los partidos nuevos
no entran, los viejos se reescriben, y todo parece funcionar.

Era lógica sin un solo test.
"""

from __future__ import annotations

import datetime as dt

import pytest

from nbastats.cli import _MES_INICIO_TEMPORADA, temporada_actual


@pytest.mark.parametrize(
    ("fecha", "esperada"),
    [
        # El corte: 30 de septiembre todavía es la temporada anterior.
        (dt.date(2026, 9, 30), "2025-26"),
        (dt.date(2026, 10, 1), "2026-27"),
        # Fin de año natural: diciembre y enero son la MISMA temporada, y es el
        # sitio donde un `hoy.year` mal puesto se cuela sin que nadie lo note.
        (dt.date(2026, 12, 31), "2026-27"),
        (dt.date(2027, 1, 1), "2026-27"),
        # Mitad de temporada y pretemporada larga.
        (dt.date(2026, 6, 13), "2025-26"),
        (dt.date(2026, 8, 26), "2025-26"),
        # Cambio de década en el sufijo: 2029-30, no "2029-3".
        (dt.date(2029, 11, 5), "2029-30"),
        # Y de siglo.
        (dt.date(2099, 11, 5), "2099-00"),
        # Bisiesto.
        (dt.date(2028, 2, 29), "2027-28"),
    ],
)
def test_el_corte_cae_donde_debe(fecha, esperada):
    assert temporada_actual(fecha) == esperada


def test_diciembre_y_enero_son_la_misma_temporada():
    """La comprobación que un `hoy.year` suelto rompería."""
    assert temporada_actual(dt.date(2026, 12, 31)) == temporada_actual(
        dt.date(2027, 1, 1)
    )


def test_el_sufijo_siempre_tiene_dos_cifras():
    for anio in (2008, 2009, 2019, 2029, 2099):
        temporada = temporada_actual(dt.date(anio, 11, 1))
        assert len(temporada) == 7, temporada
        assert temporada[4] == "-"


def test_nunca_retrocede_al_avanzar_el_tiempo():
    """Un día más nunca puede dar una temporada anterior."""
    fecha = dt.date(2025, 1, 1)
    anterior = temporada_actual(fecha)
    for _ in range(1200):
        fecha += dt.timedelta(days=1)
        actual = temporada_actual(fecha)
        assert actual >= anterior, f"retrocedió el {fecha}: {anterior} -> {actual}"
        anterior = actual


def test_el_mes_de_corte_es_octubre():
    """Si alguien lo mueve, que sea a propósito: la NBA empieza en octubre."""
    assert _MES_INICIO_TEMPORADA == 10


def test_sin_argumento_usa_hoy():
    assert temporada_actual() == temporada_actual(dt.date.today())
