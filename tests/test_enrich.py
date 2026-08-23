"""Tests de la detección de sedes neutrales."""

from __future__ import annotations

import pytest

from nbastats.ingest.enrich import is_neutral_site


def juego(**kw):
    base = {"isNeutral": False, "gameLabel": "", "gameSubLabel": "", "gameSubtype": ""}
    return base | kw


class TestSedeNeutral:
    def test_senal_directa_de_la_api(self):
        assert is_neutral_site(juego(isNeutral=True))

    @pytest.mark.parametrize(
        "etiqueta",
        ["NBA Paris Game", "NBA Mexico City Game", "NBA Abu Dhabi Game",
         "NBA London Game", "NBA Berlin Game"],
    )
    def test_partidos_internacionales_por_etiqueta(self, etiqueta):
        # Necesario para 2023-24, donde `isNeutral` aún no estaba poblado.
        assert is_neutral_site(juego(gameLabel=etiqueta))

    @pytest.mark.parametrize("ronda", ["East Semifinal", "West Semifinal", "Championship"])
    def test_nba_cup_desde_semifinales_es_las_vegas(self, ronda):
        assert is_neutral_site(
            juego(gameLabel="Emirates NBA Cup", gameSubLabel=ronda,
                  gameSubtype="in-season-knockout")
        )

    @pytest.mark.parametrize("ronda", ["East Quarterfinal", "West Quarterfinal"])
    def test_los_cuartos_de_la_nba_cup_NO_son_sede_neutral(self, ronda):
        """El bug que motivó este test.

        Los cuartos de la NBA Cup se juegan en la pista del mejor clasificado.
        Con el patrón sin `\\b`, "final" casaba dentro de "Quarterfinal" y los 4
        cuartos de cada temporada se marcaban como neutrales — contradiciendo el
        `isNeutral=False` que la propia API devuelve para ellos.
        """
        assert not is_neutral_site(
            juego(gameLabel="Emirates NBA Cup", gameSubLabel=ronda,
                  gameSubtype="in-season-knockout")
        )

    def test_partido_normal(self):
        assert not is_neutral_site(juego())

    def test_etiqueta_sin_ciudad_no_basta(self):
        # "Emirates NBA Cup" en fase de grupos se juega en casa.
        assert not is_neutral_site(juego(gameLabel="Emirates NBA Cup"))

    def test_campos_ausentes_no_revientan(self):
        assert not is_neutral_site({})
        assert not is_neutral_site({"gameLabel": None, "gameSubLabel": None})
