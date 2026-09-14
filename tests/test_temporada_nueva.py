"""Lo que pasa cuando existe una temporada que todavía no se ha jugado.

En verano hay dos datos nuevos —las plantillas con los fichajes y el
calendario— y cero partidos. Es un estado que el proyecto no tenía previsto y
en el que dos reglas razonables dejan de serlo:

1. «Guarda la clasificación que devuelva la API»: en julio son 30 equipos a
   0-0, y como la temporada por defecto se resuelve con `MAX(season_id)`, eso
   basta para que toda la aplicación enseñe un 0-0 en vez del récord de la
   última temporada jugada.
2. «Descarta al jugador de plantilla que no esté en la base»: mirando hacia
   atrás protege de inventar jugadores; mirando hacia delante borra justo los
   fichajes, que por definición aún no han jugado.
"""

from __future__ import annotations

from nbastats.ingest.teams import _ya_se_jugo


def equipo(wins=0, losses=0):
    return {"wins": wins, "losses": losses}


class TestClasificacionSinJugar:
    def test_treinta_equipos_a_cero_no_es_una_clasificacion(self):
        assert not _ya_se_jugo([equipo() for _ in range(30)])

    def test_un_solo_partido_jugado_ya_la_hace_valida(self):
        """El criterio es el dato, no una fecha escrita a mano."""
        filas = [equipo() for _ in range(29)] + [equipo(wins=1)]
        assert _ya_se_jugo(filas)

    def test_una_derrota_tambien_cuenta(self):
        assert _ya_se_jugo([equipo(losses=1)])

    def test_los_nulos_no_revientan_la_cuenta(self):
        """La fuente deja campos vacíos con más frecuencia de la que promete."""
        assert not _ya_se_jugo([{"wins": None, "losses": None}])

    def test_una_temporada_terminada_es_valida(self):
        assert _ya_se_jugo([equipo(wins=64, losses=18)])
