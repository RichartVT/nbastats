"""Tests de las métricas normalizadas."""

from __future__ import annotations

import pytest

from nbastats.analysis.rates import (
    effective_fg_pct,
    game_score,
    per_36,
    per_100_possessions,
    possessions_estimate,
    true_shooting_pct,
    usage_rate,
    z_score,
)


class TestTrueShooting:
    def test_valor_conocido(self):
        # 30 puntos con 20 tiros de campo y 10 libres.
        # TS% = 30 / (2 * (20 + 0.44*10)) = 30 / 48.8
        assert true_shooting_pct(30, 20, 10) == pytest.approx(30 / 48.8)

    def test_premia_el_triple_sobre_la_media_distancia(self):
        # Mismos intentos, más puntos: el que mete triples sale mejor.
        dos_puntos = true_shooting_pct(20, 20, 0)
        triples = true_shooting_pct(30, 20, 0)
        assert triples > dos_puntos

    def test_sin_intentos_devuelve_none(self):
        assert true_shooting_pct(0, 0, 0) is None

    def test_none_se_propaga(self):
        assert true_shooting_pct(None, 20, 10) is None


class TestEffectiveFg:
    def test_valor_conocido(self):
        # 10 anotados de 20, 4 de ellos triples: (10 + 2) / 20
        assert effective_fg_pct(10, 4, 20) == pytest.approx(0.6)

    def test_sin_triples_coincide_con_fg_pct(self):
        assert effective_fg_pct(10, 0, 20) == pytest.approx(0.5)

    def test_division_por_cero(self):
        assert effective_fg_pct(0, 0, 0) is None


class TestPerMinuteRates:
    def test_per_36_escala_correctamente(self):
        # 20 puntos en 24 minutos -> 30 puntos por 36.
        assert per_36(20, 24 * 60) == pytest.approx(30.0)

    def test_per_36_es_identidad_en_36_minutos(self):
        assert per_36(25, 36 * 60) == pytest.approx(25.0)

    def test_per_36_sin_minutos_devuelve_none(self):
        # Este es el punto: un DNP no vale 0 per-36, no vale nada.
        assert per_36(0, 0) is None
        assert per_36(10, None) is None

    def test_per_100(self):
        assert per_100_possessions(25, 100) == pytest.approx(25.0)
        assert per_100_possessions(25, 50) == pytest.approx(50.0)
        assert per_100_possessions(25, 0) is None


class TestPossessions:
    def test_formula_estandar(self):
        # 88 - 10 + 14 + 0.44*25
        assert possessions_estimate(88, 25, 10, 14) == pytest.approx(103.0)

    def test_none_se_propaga(self):
        assert possessions_estimate(88, None, 10, 14) is None


class TestUsageRate:
    def test_jugador_que_usa_su_parte_proporcional(self):
        # El jugador hace 1/5 de las jugadas en 1/5 de los minutos de equipo.
        usg = usage_rate(
            fga=20, fta=10, tov=4, seconds_played=48 * 60,
            team_fga=100, team_fta=50, team_tov=20, team_seconds=5 * 48 * 60,
        )
        assert usg == pytest.approx(0.2, abs=0.01)

    def test_sin_minutos(self):
        assert usage_rate(20, 10, 4, 0, 100, 50, 20, 14400) is None


class TestGameScore:
    def test_linea_conocida(self):
        gs = game_score(
            pts=30, fgm=10, fga=20, ftm=8, fta=10, oreb=2, dreb=6,
            stl=2, ast=8, blk=1, pf=3, tov=4,
        )
        assert gs == pytest.approx(25.5)

    def test_partido_vacio(self):
        assert game_score(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0) == pytest.approx(0.0)

    def test_none_se_propaga(self):
        assert game_score(30, None, 20, 8, 10, 2, 6, 2, 8, 1, 3, 4) is None


class TestZScore:
    def test_calculo(self):
        assert z_score(25.0, 20.0, 5.0) == pytest.approx(1.0)
        assert z_score(15.0, 20.0, 5.0) == pytest.approx(-1.0)

    def test_desviacion_cero(self):
        assert z_score(25.0, 20.0, 0.0) is None
