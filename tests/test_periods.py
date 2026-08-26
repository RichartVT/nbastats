"""Tests del box score por periodo.

Cubren las dos cosas que pueden romperse en silencio: el mapeo de una fila de
`PlayerGameLogs` a la tabla, y el etiquetado y orden de los cuartos.

El cuadre contra `player_game_stats` no se prueba aquí porque necesita base de
datos: vive en `ingest.periods.verificar_cuadre()` y lo ejecuta el propio
comando de CLI al terminar la carga.
"""

from __future__ import annotations

import pytest

from nbastats.api.catalog import STATS, STATS_POR_CUARTO, Stat
from nbastats.api.queries import _etiqueta_cuarto, _orden_cuarto
from nbastats.ingest.periods import _fila

VALIDOS = {"0022400306"}

FILA_CRUDA = {
    "PLAYER_ID": 1630528,
    "GAME_ID": "0022400306",
    "TEAM_ID": 1610612748,
    "MIN": 12.0,
    "MIN_SEC": "11:32",
    "PTS": 15, "FGM": 6, "FGA": 11, "FG3M": 1, "FG3A": 3, "FTM": 2, "FTA": 2,
    "OREB": 1, "DREB": 2, "REB": 3, "AST": 1, "STL": 0, "BLK": 1, "TOV": 2,
    "PF": 3, "PLUS_MINUS": 7,
}


class TestMapeoDeFila:
    def test_campos_basicos(self):
        f = _fila(FILA_CRUDA, 4, VALIDOS)
        assert f["game_id"] == "0022400306"
        assert f["player_id"] == 1630528
        assert f["period"] == 4
        assert f["pts"] == 15

    def test_prefiere_min_sec_por_precision(self):
        """MIN llega como 12.0 y MIN_SEC como '11:32'. El segundo es el bueno:
        redondear a minutos enteros descuadraría la suma contra
        `player_game_stats.seconds_played`."""
        assert _fila(FILA_CRUDA, 4, VALIDOS)["seconds_played"] == 692

    def test_cae_a_min_si_no_hay_min_sec(self):
        crudo = {**FILA_CRUDA, "MIN_SEC": None}
        assert _fila(crudo, 1, VALIDOS)["seconds_played"] == 720

    def test_descarta_partidos_que_no_estan_en_games(self):
        """Los ids del All-Star y de la final de la NBA Cup se cuelan en algunas
        respuestas y violarían la clave ajena."""
        assert _fila({**FILA_CRUDA, "GAME_ID": "0032400001"}, 1, VALIDOS) is None

    def test_no_se_inventan_tasas(self):
        """Sobre un cuarto, un porcentaje es una razón que alguien acabaría
        promediando. Solo viajan totales y segundos."""
        f = _fila(FILA_CRUDA, 1, VALIDOS)
        assert not any(k.endswith("_pct") or k.endswith("_36") for k in f)


class TestEtiquetasDeCuarto:
    @pytest.mark.parametrize(
        ("period", "esperado"),
        [(1, "1er cuarto"), (2, "2º cuarto"), (3, "3º cuarto"), (4, "4º cuarto")],
    )
    def test_cuartos(self, period, esperado):
        assert _etiqueta_cuarto(period) == esperado

    @pytest.mark.parametrize(
        ("period", "esperado"), [(5, "1ª prórroga"), (6, "2ª prórroga"), (7, "3ª prórroga")]
    )
    def test_las_prorrogas_se_renumeran_desde_uno(self, period, esperado):
        """Nadie lee un partido como "periodo 6": el número de periodo deja de
        significar nada para quien mira."""
        assert _etiqueta_cuarto(period) == esperado

    def test_orden_natural_del_partido(self):
        etiquetas = [_etiqueta_cuarto(n) for n in (5, 2, 6, 1, 4, 3)]
        assert sorted(etiquetas, key=_orden_cuarto) == [
            "1er cuarto", "2º cuarto", "3º cuarto", "4º cuarto",
            "1ª prórroga", "2ª prórroga",
        ]

    def test_las_prorrogas_van_despues_de_los_cuartos(self):
        assert _orden_cuarto("1ª prórroga") > _orden_cuarto("4º cuarto")


class TestEstadisticasAdmisibles:
    def test_solo_totales_por_cuarto(self):
        """Las tasas no existen en `player_period_stats` y pedirlas debe ser un
        error de la petición, no un hueco lleno de nulos."""
        assert all(not STATS[s].is_rate for s in STATS_POR_CUARTO)

    def test_las_habituales_estan(self):
        for s in (Stat.PTS, Stat.REB, Stat.AST, Stat.MINUTES):
            assert s in STATS_POR_CUARTO

    def test_las_tasas_no_estan(self):
        for s in (Stat.PTS_36, Stat.TS, Stat.USG, Stat.GAME_SCORE):
            assert s not in STATS_POR_CUARTO
