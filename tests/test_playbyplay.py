"""Tests del play-by-play.

Cubren lo que se aprendió cargándolo de verdad, que no era lo que parecía desde
la documentación: la clave no es la que se creía y `personId` no siempre es un
jugador. Los dos fallos reventaron en la primera prueba de carga; estos tests
existen para que no vuelvan en silencio.
"""

from __future__ import annotations

import pytest

from nbastats.ingest.playbyplay import (
    SEGUNDOS_CUARTO,
    SEGUNDOS_PRORROGA,
    _fila,
    _jugador,
    _resultado_tiro,
    elapsed_seconds,
    parse_clock,
)

JUGADORES = frozenset({203999, 1628983})


class TestReloj:
    @pytest.mark.parametrize(
        ("texto", "segundos"),
        [("PT12M00.00S", 720), ("PT10M24.00S", 624), ("PT00M00.00S", 0), ("PT00M00.60S", 0)],
    )
    def test_iso8601_a_segundos_restantes(self, texto, segundos):
        assert parse_clock(texto) == segundos

    @pytest.mark.parametrize("basura", [None, "", "10:24", "PTXM"])
    def test_lo_que_no_se_entiende_es_none_no_cero(self, basura):
        """Cero segundos restantes es el final del periodo; no saberlo es otra
        cosa. Confundirlos metería eventos falsos en la bocina."""
        assert parse_clock(basura) is None


class TestTranscurrido:
    @pytest.mark.parametrize(
        ("period", "clock", "esperado"),
        [(1, 720, 0), (1, 0, 720), (2, 720, 720), (4, 0, 2880)],
    )
    def test_cuartos(self, period, clock, esperado):
        assert elapsed_seconds(period, clock) == esperado

    def test_la_prorroga_dura_cinco_minutos_no_doce(self):
        """El fallo clásico: asumir 720 en la prórroga desplaza todo lo que
        viene después, y el 6,5% de los partidos tiene al menos una."""
        assert elapsed_seconds(5, SEGUNDOS_PRORROGA) == 4 * SEGUNDOS_CUARTO
        assert elapsed_seconds(5, 0) == 4 * SEGUNDOS_CUARTO + SEGUNDOS_PRORROGA
        assert elapsed_seconds(6, 0) == 4 * SEGUNDOS_CUARTO + 2 * SEGUNDOS_PRORROGA

    def test_es_monotono_a_lo_largo_del_partido(self):
        instantes = [
            elapsed_seconds(p, c)
            for p, c in [(1, 720), (1, 300), (2, 400), (3, 100), (4, 0), (5, 200), (6, 0)]
        ]
        assert instantes == sorted(instantes)

    def test_sin_reloj_no_hay_transcurrido(self):
        assert elapsed_seconds(1, None) is None


class TestPersonIdNoSiempreEsJugador:
    """En los tiempos muertos `personId` lleva el id del EQUIPO, y en las
    técnicas el del ÁRBITRO. Los tres casos reventaron la clave ajena en la
    primera carga real."""

    def test_jugador_conocido_pasa(self):
        assert _jugador(203999, JUGADORES) == 203999

    @pytest.mark.parametrize("ajeno", [1610612759, 320, 544, 739])
    def test_equipos_y_arbitros_van_a_null(self, ajeno):
        assert _jugador(ajeno, JUGADORES) is None

    def test_el_cero_de_los_eventos_sin_dueno(self):
        assert _jugador(0, JUGADORES) is None

    def test_sin_censo_no_se_filtra(self):
        """Con censo vacío se acepta todo: permite usar la función en tests y
        en cargas parciales sin tener que montar la tabla de jugadores."""
        assert _jugador(999, frozenset()) == 999


class TestResultadoDeTiro:
    def test_anotado_y_fallado(self):
        assert _resultado_tiro("Made") is True
        assert _resultado_tiro("Missed") is False

    @pytest.mark.parametrize("vacio", [None, "", "   "])
    def test_lo_que_no_es_tiro_no_es_fallo(self, vacio):
        """None y False son cosas distintas: un rebote no es un tiro fallado."""
        assert _resultado_tiro(vacio) is None


class TestFila:
    def base(self, **extra):
        return {
            "actionId": 42, "actionNumber": 57, "period": 1,
            "clock": "PT07M32.00S", "teamId": 1610612759, "personId": 203999,
            "actionType": "Missed Shot", "subType": "Driving Layup Shot",
            "description": "MISS Castle 6' Driving Layup", "scoreHome": "90",
            "scoreAway": "94", "isFieldGoal": 1, "shotResult": "Missed",
            "shotValue": 2, "shotDistance": 6, "xLegacy": -21, "yLegacy": 52,
            **extra,
        }

    def test_la_clave_es_action_id(self):
        """Los eventos ligados —un tiro y el tapón que lo causó— comparten
        `action_number` y solo `action_id` los distingue."""
        f = _fila("0022500828", self.base(), JUGADORES)
        assert f["action_id"] == 42
        assert f["action_number"] == 57

    def test_sin_action_id_no_hay_fila(self):
        assert _fila("g", self.base(actionId=None), JUGADORES) is None

    def test_sin_periodo_valido_no_hay_fila(self):
        assert _fila("g", self.base(period=0), JUGADORES) is None

    def test_no_se_guarda_lo_derivable(self):
        """teamTricode, playerName y location salen de un JOIN o de comparar
        con el local. Guardarlos son ~90 MB de copia."""
        f = _fila("g", self.base(teamTricode="SAS", playerName="Castle"), JUGADORES)
        for sobra in ("teamTricode", "playerName", "playerNameI", "location", "pointsTotal"):
            assert sobra not in f

    def test_el_marcador_llega_como_texto(self):
        f = _fila("g", self.base(), JUGADORES)
        assert f["score_home"] == 90 and f["score_away"] == 94
