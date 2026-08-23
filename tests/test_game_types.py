"""Tests del tipo de partido.

Las etiquetas de este fichero NO son inventadas: son las 55 combinaciones
reales que aparecen en las 5 temporadas cargadas. Escribirlas a mano habría
dejado fuera precisamente los casos que rompen —el cambio de formato entre
temporadas y los patrocinadores.
"""

from __future__ import annotations

import pytest

from nbastats.analysis.game_types import describe_game


class TestTemporadaRegular:
    def test_sin_etiqueta(self):
        g = describe_game("regular")
        assert (g.key, g.label, g.is_postseason) == ("regular", "Temporada regular", False)

    @pytest.mark.parametrize("vacio", [None, "", "   "])
    def test_etiqueta_vacia(self, vacio):
        assert describe_game("regular", vacio).label == "Temporada regular"


class TestNBACup:
    @pytest.mark.parametrize(
        ("sublabel", "esperado"),
        [
            ("East Group A", "NBA Cup · Grupo"),
            ("West Group C", "NBA Cup · Grupo"),
            ("East Quarterfinal", "NBA Cup · Cuartos"),
            ("West Semifinal", "NBA Cup · Semifinal"),
            ("Championship", "NBA Cup · Final"),
            ("", "NBA Cup"),
        ],
    )
    def test_rondas(self, sublabel, esperado):
        assert describe_game("regular", "Emirates NBA Cup", sublabel).label == esperado

    def test_cuartos_no_se_leen_como_final(self):
        """El bug que motivó los límites de palabra.

        Sin `\\b`, "final" casa dentro de "Quarterfinal". Ese error ya marcó
        una vez los cuartos como jugados en sede neutral, contradiciendo el
        `isNeutral=False` que devuelve la propia API.
        """
        g = describe_game("regular", "Emirates NBA Cup", "East Quarterfinal")
        assert g.label == "NBA Cup · Cuartos"

    def test_la_cup_NO_es_postemporada(self):
        # Cuenta para la clasificación de temporada regular: son 66 de los
        # 1.230 partidos de cada año.
        assert not describe_game("regular", "Emirates NBA Cup", "East Group A").is_postseason


class TestPlayoffs:
    @pytest.mark.parametrize(
        ("etiqueta", "esperado"),
        [
            # Formato de 2021-22 a 2023-24: con guion.
            ("East - First Round", "Primera ronda Este"),
            ("West - Conf. Semifinals", "Semifinales Oeste"),
            ("East - Conf. Finals", "Final de conferencia Este"),
            # Formato desde 2024-25: sin guion.
            ("West First Round", "Primera ronda Oeste"),
            ("East Conf. Semifinals", "Semifinales Este"),
            ("West Conf. Finals", "Final de conferencia Oeste"),
            # Las Finales no son de conferencia.
            ("NBA Finals", "Finales NBA"),
        ],
    )
    def test_rondas_reales(self, etiqueta, esperado):
        g = describe_game("playoffs", etiqueta)
        assert g.label == esperado
        assert g.is_postseason

    def test_semifinales_no_se_leen_como_final(self):
        """'Conf. Semifinals' contiene 'Finals'.

        Por eso las semifinales se prueban ANTES que las finales en la lista de
        patrones: al revés, toda semifinal se etiquetaría como final.
        """
        assert describe_game("playoffs", "East Conf. Semifinals").label == "Semifinales Este"
        assert describe_game("playoffs", "East - Conf. Semifinals").label == "Semifinales Este"

    def test_sin_etiqueta_cae_a_generico(self):
        assert describe_game("playoffs").label == "Playoffs"

    @pytest.mark.parametrize(
        ("etiqueta", "sublabel", "esperado"),
        [
            ("NBA Finals", "Game 7", "Finales NBA · G7"),
            ("West Conf. Finals", "Game 1", "Final de conferencia Oeste · G1"),
            ("East First Round", "Game 4", "Primera ronda Este · G4"),
            # Sin número: la etiqueta se queda sin sufijo, no con "· G".
            ("NBA Finals", "", "Finales NBA"),
            ("NBA Finals", None, "Finales NBA"),
        ],
    )
    def test_numero_de_partido(self, etiqueta, sublabel, esperado):
        """El sublabel trae el número de eliminatoria: no es lo mismo un G1 que un G7."""
        assert describe_game("playoffs", etiqueta, sublabel).label == esperado


class TestPlayIn:
    @pytest.mark.parametrize(
        ("etiqueta", "esperado"),
        [
            ("East Play-In", "Play-In Este"),
            ("West Play-In", "Play-In Oeste"),
            # Con patrocinador y sin conferencia (formato de 2024-25).
            ("SoFi Play-In Tournament", "Play-In"),
            ("", "Play-In"),
        ],
    )
    def test_variantes(self, etiqueta, esperado):
        g = describe_game("playin", etiqueta)
        assert g.label == esperado
        assert g.is_postseason


class TestInternacionales:
    @pytest.mark.parametrize(
        ("etiqueta", "esperado"),
        [
            ("NBA Paris Game", "París"),
            ("NBA Paris Games", "París"),          # plural, visto en 2024-25
            ("NBA Mexico City Game", "Ciudad de México"),
            ("NBA Berlin Game", "Berlín"),
            ("NBA London Game", "Londres"),
        ],
    )
    def test_ciudades_reales(self, etiqueta, esperado):
        g = describe_game("regular", etiqueta)
        assert (g.key, g.label) == ("international", esperado)


class TestPatrocinadores:
    @pytest.mark.parametrize(
        "etiqueta",
        ["Emirates NBA Cup", "NBA Cup", "Michelob ULTRA NBA Cup"],
    )
    def test_el_patrocinador_no_cambia_el_tipo(self, etiqueta):
        # Los patrocinadores cambian cada temporada; el tipo de partido no.
        assert describe_game("regular", etiqueta, "East Group A").key == "cup"


class TestEtiquetasDesconocidas:
    @pytest.mark.parametrize(
        "etiqueta", ["AWS NBA Rivals Week", "NBA Pioneers Classic"]
    )
    def test_eventos_reales_no_previstos_se_muestran(self, etiqueta):
        """Eventos que existen en los datos y que no anticipé.

        Se muestran tal cual en vez de tragarse: si la NBA inventa un formato
        nuevo, preferimos verlo en pantalla a que desaparezca sin rastro.
        """
        g = describe_game("regular", etiqueta)
        assert g.key == "labeled"
        # El patrocinador sí se quita; el nombre del evento se conserva.
        assert "NBA" in g.label

    def test_etiqueta_muy_larga_se_recorta(self):
        assert len(describe_game("regular", "X" * 200).label) == 40


class TestCasosLimite:
    def test_pretemporada(self):
        assert describe_game("preseason").label == "Pretemporada"

    def test_la_etiqueta_no_pisa_al_tipo_de_temporada(self):
        # Un partido de playoffs es playoffs aunque lleve etiqueta de Cup.
        assert describe_game("playoffs", "Emirates NBA Cup").is_postseason
