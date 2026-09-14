"""Fichajes, traspasos y cortes con la temporada en marcha.

POR QUÉ NO SE HABÍA PROBADO. La actualización diaria nunca había corrido
durante una temporada activa: las cinco temporadas cargadas se trajeron de una
sola vez, ya con los traspasos resueltos. En ese escenario la ingesta de
plantillas es correcta por accidente — nunca ve cambiar nada.

En cuanto empieza a correr a diario, aparecen tres cosas que antes no existían:
un jugador puede dejar de estar en un equipo, puede aparecer en otro, y su
ficha tiene que seguirle. Esto prueba las tres, y sobre todo prueba los
guardarraíles: la diferencia entre «ya no está en el equipo» y «hoy la NBA no
nos ha contestado», que sin cuidado se convierten en la misma cosa y vacían
media liga.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from nbastats.cli import (
    temporada_actual,
    temporada_siguiente,
    temporadas_sin_partidos,
)
from nbastats.ingest.teams import _ids_de_plantilla, _limpiar_plantillas


def jugador(pid, nombre="Un Jugador"):
    return {"PLAYER_ID": pid, "PLAYER": nombre, "NUM": "0", "POSITION": "G"}


def respuesta(*jugadores):
    return {"CommonTeamRoster": list(jugadores)}


class TestLeerLaPlantilla:
    def test_saca_los_ids(self):
        assert _ids_de_plantilla(respuesta(jugador(1), jugador(2))) == {1, 2}

    def test_una_plantilla_vacia_no_autoriza_a_borrar(self):
        """El guardarraíl que separa un hueco de la fuente de un equipo vacío.

        Un conjunto vacío no entra en `vigentes`, y sin entrar ahí no se borra
        nada de ese equipo. Un equipo NBA nunca tiene cero jugadores; si la
        respuesta llega así, el dato que falta es el suyo, no el nuestro.
        """
        assert _ids_de_plantilla(respuesta()) == set()
        assert _ids_de_plantilla({}) == set()

    def test_una_ficha_sin_id_no_cuenta(self):
        assert _ids_de_plantilla(respuesta(jugador(None), jugador(7))) == {7}

    def test_los_ids_llegan_como_numero(self):
        """La fuente los manda a veces como texto y a veces como float."""
        assert _ids_de_plantilla(respuesta(jugador("2544"), jugador(1629029.0))) == {
            2544,
            1629029,
        }


class TestNoSeBorraLoQueNoSeSabe:
    """El guardarraíl que convierte un fallo de red en una plantilla vacía.

    `ingest_rosters` ya hacía `continue` cuando un equipo no contestaba, sin
    dejar rastro. Con el borrado añadido, eso bastaría para que un corte de red
    de diez segundos vaciara la plantilla entera de ese equipo: nadie de los
    suyos vendría en la respuesta, así que «nadie» se leería como «ya no está
    ninguno».
    """

    class _SesionFalsa:
        """Registra los DELETE en vez de ejecutarlos."""

        def __init__(self):
            self.borrados = []

        def execute(self, stmt):
            self.borrados.append(stmt)
            return SimpleNamespace(rowcount=0)

    def test_un_equipo_que_no_contesto_no_se_toca(self):
        sesion = self._SesionFalsa()
        # Solo un equipo en `vigentes`: los otros 29 fallaron o llegaron vacíos.
        _limpiar_plantillas(sesion, "2026-27", {1610612747: {1, 2, 3}})
        assert len(sesion.borrados) == 1, "se tocó un equipo del que no sabemos nada"

    def test_sin_ninguna_respuesta_no_se_borra_nada(self):
        """El caso extremo: la NBA no contesta a nadie."""
        sesion = self._SesionFalsa()
        assert _limpiar_plantillas(sesion, "2026-27", {}) == 0
        assert sesion.borrados == []


class TestElCorteDeTemporada:
    """Plantillas y calendario no siguen el mismo calendario que los partidos."""

    def test_la_siguiente_entra_si_la_nba_ya_publico_su_calendario(self):
        assert temporadas_sin_partidos("2025-26", {"2025-26", "2026-27"}) == [
            "2025-26",
            "2026-27",
        ]

    def test_y_no_entra_si_todavia_no(self):
        """El criterio es el dato, no una fecha escrita a mano."""
        assert temporadas_sin_partidos("2025-26", {"2025-26"}) == ["2025-26"]

    def test_el_bug_que_motivo_esto(self):
        """En septiembre, el corte de octubre apunta a una temporada terminada.

        El 14 de septiembre de 2026 la temporada "actual" seguía siendo la
        2025-26, acabada en junio, mientras los fichajes se firmaban en la
        2026-27. Sin esto, los movimientos de julio a septiembre no entraban
        hasta octubre.
        """
        septiembre = temporada_actual(dt.date(2026, 9, 14))
        assert septiembre == "2025-26"
        assert temporadas_sin_partidos(septiembre, {"2026-27"}) == [
            "2025-26",
            "2026-27",
        ]

    def test_en_plena_temporada_no_hay_siguiente_que_pedir(self):
        enero = temporada_actual(dt.date(2027, 1, 15))
        assert enero == "2026-27"
        assert temporadas_sin_partidos(enero, {"2025-26", "2026-27"}) == ["2026-27"]

    @pytest.mark.parametrize(
        ("season", "esperada"),
        [("2025-26", "2026-27"), ("2029-30", "2030-31"), ("2099-00", "2100-01")],
    )
    def test_la_siguiente_se_calcula_bien(self, season, esperada):
        assert temporada_siguiente(season) == esperada


# =========================================================================
# Con base de datos
# =========================================================================
#
# SE SALTAN SIN POSTGRES, igual que el cruce Python ↔ SQL: el resto de la suite
# es pura y corre en dos segundos, y romper eso por estos tres no sale a cuenta.


def _conn():
    pytest.importorskip("sqlalchemy")
    try:
        from nbastats.db.session import get_engine

        engine = get_engine()
        with engine.connect() as c:
            c.execute(__import__("sqlalchemy").text("SELECT 1"))
        return engine
    except Exception as e:  # noqa: BLE001 — sin base, estos tests no aplican
        pytest.skip(f"sin base de datos: {type(e).__name__}")


def _filas(engine, sql: str):
    import sqlalchemy as sa

    with engine.connect() as c:
        return [dict(f) for f in c.execute(sa.text(sql)).mappings()]


class TestLaBaseQuedaCoherente:
    """Las tres invariantes que este cambio tiene que sostener."""

    def test_nadie_esta_en_dos_plantillas_a_la_vez(self):
        """Lo que produciría el upsert sin borrado en cuanto haya un traspaso."""
        engine = _conn()
        (f,) = _filas(engine, """
            SELECT count(*) AS n FROM (
              SELECT season_id, player_id FROM team_season_rosters
              GROUP BY 1, 2 HAVING count(*) > 1
            ) x
        """)
        assert f["n"] == 0, "hay jugadores en dos equipos la misma temporada"

    def test_quien_esta_en_plantilla_apunta_a_su_equipo(self):
        """`current_team_id` se congelaba: 23 de 588 apuntaban al equipo viejo."""
        engine = _conn()
        (f,) = _filas(engine, """
            SELECT count(*) AS n
            FROM players p
            JOIN team_season_rosters r ON r.player_id = p.player_id
            WHERE r.season_id = (SELECT MAX(season_id) FROM team_season_rosters)
              AND p.current_team_id IS DISTINCT FROM r.team_id
        """)
        assert f["n"] == 0, "hay jugadores con el equipo actual equivocado"

    def test_quien_esta_en_plantilla_no_figura_como_agente_libre(self):
        """`roster_status` igual: 12 fichados seguían marcados `Inactive`."""
        engine = _conn()
        (f,) = _filas(engine, """
            SELECT count(*) AS n
            FROM players p
            JOIN team_season_rosters r ON r.player_id = p.player_id
            WHERE r.season_id = (SELECT MAX(season_id) FROM team_season_rosters)
              AND p.roster_status IS DISTINCT FROM 'Active'
        """)
        assert f["n"] == 0, "hay jugadores con equipo marcados como sin equipo"
