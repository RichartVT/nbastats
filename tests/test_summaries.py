"""Tests del resumen por partido (marcador por cuarto, árbitros, ficha).

No tocan la red ni la base: prueban las funciones puras que traducen la
respuesta de `BoxScoreSummaryV3` a filas. Los datos de ejemplo son la forma
REAL del endpoint, copiada de la respuesta del partido 0022200168 (Thunder,
dos prórrogas) y del 0022400306.
"""

from __future__ import annotations

import pytest

from nbastats.ingest.summaries import _arbitros, _cabecera, _entero, _periodos

# Respuesta real: 4 cuartos y 2 prórrogas.
EQUIPO_CON_PRORROGA = {
    "teamId": 1610612760,
    "teamTricode": "OKC",
    "periods": [
        {"period": 1, "periodType": "REGULAR", "score": 27},
        {"period": 2, "periodType": "REGULAR", "score": 28},
        {"period": 3, "periodType": "REGULAR", "score": 32},
        {"period": 4, "periodType": "REGULAR", "score": 32},
        {"period": 5, "periodType": "OVERTIME", "score": 7},
        {"period": 6, "periodType": "OVERTIME", "score": 6},
    ],
}

EQUIPO_NORMAL = {
    "teamId": 1610612763,
    "periods": [
        {"period": 1, "periodType": "REGULAR", "score": 28},
        {"period": 2, "periodType": "REGULAR", "score": 34},
        {"period": 3, "periodType": "REGULAR", "score": 40},
        {"period": 4, "periodType": "REGULAR", "score": 34},
    ],
}


class TestPeriodos:
    def test_una_fila_por_periodo(self):
        filas = _periodos("0022200168", EQUIPO_CON_PRORROGA)
        assert len(filas) == 6
        assert [f["period"] for f in filas] == [1, 2, 3, 4, 5, 6]

    def test_los_puntos_suman_el_total_del_equipo(self):
        """Es la comprobación que se corre luego contra `team_game_stats`."""
        assert sum(f["points"] for f in _periodos("g", EQUIPO_CON_PRORROGA)) == 132

    def test_la_prorroga_la_dice_la_fuente(self):
        """`is_overtime` sale de `periodType`, no de `period > 4`. Una regla
        nuestra dejaría de valer el día que cambie el formato."""
        filas = _periodos("g", EQUIPO_CON_PRORROGA)
        assert [f["is_overtime"] for f in filas] == [False, False, False, False, True, True]

    def test_partido_sin_prorroga(self):
        filas = _periodos("g", EQUIPO_NORMAL)
        assert len(filas) == 4
        assert not any(f["is_overtime"] for f in filas)

    def test_sin_team_id_no_se_inventa_fila(self):
        """Sin equipo, la fila violaría la clave ajena. Mejor ninguna."""
        assert _periodos("g", {"periods": EQUIPO_NORMAL["periods"]}) == []

    def test_periodo_incompleto_se_descarta(self):
        equipo = {"teamId": 1, "periods": [{"period": 1, "periodType": "REGULAR"}]}
        assert _periodos("g", equipo) == []

    def test_equipo_vacio(self):
        assert _periodos("g", {}) == []


class TestCabecera:
    def test_cuenta_las_prorrogas_en_vez_de_calcularlas(self):
        """Hasta ahora `ot_periods` se INFERÍA con round((MIN-48)/5). Aquí se
        cuentan los periodos que la fuente marca como prórroga."""
        filas = _periodos("g", EQUIPO_CON_PRORROGA)
        assert _cabecera("g", {}, filas)["ot_periods"] == 2

    def test_las_prorrogas_no_se_cuentan_dos_veces(self):
        """Los dos equipos aportan filas del mismo periodo 5; es UNA prórroga."""
        filas = _periodos("g", EQUIPO_CON_PRORROGA) + _periodos(
            "g", {"teamId": 99, "periods": EQUIPO_CON_PRORROGA["periods"]}
        )
        assert len(filas) == 12
        assert _cabecera("g", {}, filas)["ot_periods"] == 2

    def test_sin_prorroga(self):
        assert _cabecera("g", {}, _periodos("g", EQUIPO_NORMAL))["ot_periods"] == 0

    def test_pabellon_y_asistencia(self):
        c = _cabecera("g", {"attendance": 15180, "arena": {"arenaName": "Paycom Center"}}, [])
        assert c["arena_name"] == "Paycom Center"
        assert c["attendance"] == 15180

    def test_sin_pabellon(self):
        assert _cabecera("g", {}, [])["arena_name"] is None


class TestAsistencia:
    @pytest.mark.parametrize("valor", [0, None, "", "no disponible"])
    def test_cero_y_ausente_son_lo_mismo_null(self, valor):
        """Cero espectadores y "no lo publican" no se distinguen en la fuente,
        y una media de asistencia que cuente los ceros estaría mal. Ante la
        duda, "no hay dato" — nunca 0."""
        assert _entero(valor) is None

    def test_valor_real(self):
        assert _entero(19812) == 19812

    def test_texto_numerico(self):
        assert _entero("19812") == 19812


class TestArbitros:
    def test_extrae_los_tres(self):
        resumen = {
            "officials": [
                {"personId": 2003, "name": "Pat Fraher", "jerseyNum": "26  "},
                {"personId": 1627541, "name": "Natalie Sago", "jerseyNum": "9   "},
                {"personId": 1628487, "name": "Danielle Scott", "jerseyNum": "12"},
            ]
        }
        filas = _arbitros("g", resumen)
        assert len(filas) == 3
        assert filas[0]["name"] == "Pat Fraher"

    def test_el_dorsal_llega_con_relleno_y_se_limpia(self):
        """La API devuelve '26  ' con espacios a la derecha."""
        resumen = {"officials": [{"personId": 1, "name": "X", "jerseyNum": "26  "}]}
        assert _arbitros("g", resumen)[0]["jersey_number"] == "26"

    def test_dorsal_vacio_es_null(self):
        resumen = {"officials": [{"personId": 1, "name": "X", "jerseyNum": "   "}]}
        assert _arbitros("g", resumen)[0]["jersey_number"] is None

    def test_sin_id_no_hay_fila(self):
        assert _arbitros("g", {"officials": [{"name": "Sin id"}]}) == []

    def test_sin_arbitros(self):
        assert _arbitros("g", {}) == []
