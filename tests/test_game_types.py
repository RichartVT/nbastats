"""Tests del tipo de partido."""

from __future__ import annotations

import pytest

from nbastats.analysis.game_types import describe_game


class TestTiposBasicos:
    @pytest.mark.parametrize(
        ("season_type", "key", "label"),
        [
            ("regular", "regular", "Temporada regular"),
            ("playoffs", "playoffs", "Playoffs"),
            ("playin", "playin", "Play-In"),
            ("preseason", "preseason", "Pretemporada"),
        ],
    )
    def test_por_tipo_de_temporada(self, season_type, key, label):
        g = describe_game(season_type)
        assert (g.key, g.label) == (key, label)

    def test_postemporada_marcada(self):
        assert describe_game("playoffs").is_postseason
        assert describe_game("playin").is_postseason
        assert not describe_game("regular").is_postseason


class TestNBACup:
    @pytest.mark.parametrize(
        ("sublabel", "esperado"),
        [
            ("East Group C", "NBA Cup · Grupo"),
            ("West Group B", "NBA Cup · Grupo"),
            ("East Quarterfinal", "NBA Cup · Cuartos"),
            ("West Semifinal", "NBA Cup · Semifinal"),
            ("Championship", "NBA Cup · Final"),
            ("", "NBA Cup"),
        ],
    )
    def test_rondas(self, sublabel, esperado):
        assert describe_game("regular", "Emirates NBA Cup", sublabel).label == esperado

    def test_cuartos_no_se_confunden_con_la_final(self):
        """El bug que motivó los límites de palabra.

        Sin `\\b`, "final" casa dentro de "Quarterfinal". Ese error ya marcó
        una vez los cuartos como jugados en sede neutral, contradiciendo el
        `isNeutral=False` que devuelve la propia API.
        """
        cuartos = describe_game("regular", "Emirates NBA Cup", "East Quarterfinal")
        assert cuartos.label == "NBA Cup · Cuartos"
        assert "Final" not in cuartos.label

    def test_la_cup_NO_es_postemporada(self):
        # Cuenta para la clasificación de temporada regular.
        assert not describe_game("regular", "Emirates NBA Cup", "East Group A").is_postseason


class TestInternacionales:
    @pytest.mark.parametrize(
        ("etiqueta", "esperado"),
        [
            ("NBA Paris Game", "París"),
            ("NBA Mexico City Game", "Ciudad de México"),
            ("NBA London Game", "Londres"),
            ("NBA Abu Dhabi Game", "Abu Dabi"),
        ],
    )
    def test_ciudades(self, etiqueta, esperado):
        g = describe_game("regular", etiqueta)
        assert g.label == esperado
        assert g.key == "international"


class TestCasosLimite:
    def test_etiqueta_desconocida_se_muestra_tal_cual(self):
        # Si la NBA inventa un formato nuevo, preferimos verlo a que se pierda.
        g = describe_game("regular", "NBA Torneo Inventado")
        assert g.key == "labeled"
        assert g.label == "NBA Torneo Inventado"

    def test_etiqueta_muy_larga_se_recorta(self):
        assert len(describe_game("regular", "X" * 200).label) == 40

    def test_nulos_y_vacios(self):
        assert describe_game("regular", None, None).label == "Temporada regular"
        assert describe_game("regular", "", "").label == "Temporada regular"
        assert describe_game("regular", "   ").label == "Temporada regular"

    def test_la_etiqueta_no_pisa_a_los_playoffs(self):
        # Un partido de playoffs es playoffs aunque venga etiquetado.
        assert describe_game("playoffs", "Emirates NBA Cup").label == "Playoffs"
