"""Tests del estado del jugador.

Los cuatro casos que se comprueban aquí no son hipotéticos: son los que
aparecen en las 5 temporadas cargadas, con sus recuentos reales.

    495  Active,   última temporada 2025-26   -> Activo
      6  Active,   última temporada anterior  -> Activo, sin partidos
     93  Inactive, última temporada 2025-26   -> Agente libre
    442  Inactive, última temporada anterior  -> Fuera de la liga
"""

from __future__ import annotations

import pytest

from nbastats.analysis.player_status import describe_status
from nbastats.api.catalog import PlayerStatusFilter
from nbastats.api.queries import _CONDICION_ESTADO

ULTIMA = "2025-26"


class TestEnPlantilla:
    def test_activo_jugando(self):
        e = describe_status("Active", "2025-26", ULTIMA, "Denver Nuggets")
        assert (e.key, e.label, e.on_roster) == ("activo", "Activo", True)
        assert "Denver Nuggets" in e.note

    def test_activo_sin_partidos_esta_temporada(self):
        """Existe de verdad: ficha en vigor y ni un minuto en toda la temporada.

        Sin la nota, la fila se lee como un fallo de datos —"Activo" con 0
        partidos— cuando lo que describe es una lesión de larga duración.
        """
        e = describe_status("Active", "2024-25", ULTIMA, "Portland Trail Blazers")
        assert e.key == "activo"
        assert e.on_roster is True
        assert "sin partidos en 2025-26" in e.note

    def test_el_equipo_de_quien_esta_en_plantilla_es_el_actual(self):
        e = describe_status("Active", "2025-26", ULTIMA, "Denver Nuggets")
        assert e.team_label == "Equipo actual"


class TestSinPlantilla:
    def test_agente_libre(self):
        e = describe_status("Inactive", "2025-26", ULTIMA, "Sacramento Kings")
        assert (e.key, e.label, e.on_roster) == ("agente_libre", "Agente libre", False)
        assert "Sacramento Kings" in e.note

    def test_fuera_de_la_liga(self):
        e = describe_status("Inactive", "2022-23", ULTIMA, "Los Angeles Lakers")
        assert (e.key, e.label, e.on_roster) == ("fuera_liga", "Fuera de la liga", False)
        assert "2022-23" in e.note

    def test_nunca_se_afirma_que_este_retirado(self):
        """La liga no publica ningún campo que distinga al retirado del que
        juega en Europa. La etiqueta dice lo que sabemos y la nota lo que no."""
        e = describe_status("Inactive", "2021-22", ULTIMA)
        assert "Retirado" not in e.label
        assert "puede estar retirado" in e.note.lower()

    def test_el_equipo_de_quien_no_esta_en_plantilla_es_el_ultimo(self):
        """Es el error que esta distinción evita: el `current_team_id` de un
        jugador fuera de la liga es su ÚLTIMO equipo, y enseñarlo como actual
        lo convierte en fichaje de un equipo que no lo tiene."""
        e = describe_status("Inactive", "2021-22", ULTIMA, "Los Angeles Lakers")
        assert e.team_label == "Último equipo"

    @pytest.mark.parametrize("crudo", [None, "", "Inactive"])
    def test_solo_active_cuenta_como_plantilla(self, crudo):
        assert describe_status(crudo, "2021-22", ULTIMA).on_roster is False


class TestSinPartidos:
    def test_sin_temporadas_cargadas(self):
        e = describe_status("Inactive", None, ULTIMA)
        assert e.key == "sin_datos"
        assert e.on_roster is False


class TestCoherenciaConElSQL:
    """El filtro por estado se resuelve en SQL y las etiquetas en Python.

    Son dos sitios, así que pueden separarse. Estos tests reproducen el
    predicado SQL en Python y comprueban que clasifica igual que
    `describe_status` en toda la rejilla de casos posibles.
    """

    @staticmethod
    def _sql_equivalente(roster_status, ultima):
        activo = roster_status == "Active"
        return {
            "activo": activo,
            "agente_libre": not activo and ultima == ULTIMA,
            "fuera_liga": not activo and ultima is not None and ultima < ULTIMA,
        }

    @pytest.mark.parametrize("roster_status", ["Active", "Inactive", None])
    @pytest.mark.parametrize("ultima", ["2025-26", "2024-25", "2021-22"])
    def test_misma_clasificacion(self, roster_status, ultima):
        clave = describe_status(roster_status, ultima, ULTIMA).key
        predicados = self._sql_equivalente(roster_status, ultima)
        assert predicados[clave] is True
        for otra, valor in predicados.items():
            if otra != clave:
                assert valor is False, f"{otra} también casaría con {roster_status}/{ultima}"

    def test_el_sql_cubre_todas_las_claves_filtrables(self):
        assert set(_CONDICION_ESTADO) == {s.value for s in PlayerStatusFilter}

    def test_las_temporadas_se_comparan_como_texto(self):
        """El SQL compara `ultima_nba < :latest` con varchar. Funciona porque
        el formato 'AAAA-AA' ordena igual como texto que cronológicamente —
        pero solo mientras el siglo no cambie, así que conviene dejarlo escrito.
        """
        assert "2021-22" < "2024-25" < "2025-26"
