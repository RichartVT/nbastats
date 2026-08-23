"""Tests de las normalizaciones de ingesta."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from nbastats.db.models import SeasonType
from nbastats.ingest.transforms import (
    format_seconds,
    local_game_date,
    parse_birthdate,
    parse_game_id,
    parse_height_to_cm,
    parse_minutes,
    parse_weight_to_kg,
    season_id_from_start_year,
    season_start_year,
)


class TestParseMinutes:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("34:12", 34 * 60 + 12),
            ("0:00", 0),
            ("48:00", 2880),
            ("5:30", 330),
            # Quirk documentado de nba_api.
            ("34.000000:12", 34 * 60 + 12),
            ("7.000000:05", 7 * 60 + 5),
            # Solo minutos.
            ("34", 2040),
            (34, 2040),
            (34.5, 2070),
            # DNP y basura.
            (None, 0),
            ("", 0),
            ("   ", 0),
            ("None", 0),
            ("nan", 0),
            ("-", 0),
            ("no soy un tiempo", 0),
            (-5, 0),
            ("-3:00", 0),
        ],
    )
    def test_parse(self, value, expected):
        assert parse_minutes(value) == expected

    def test_nan_float(self):
        assert parse_minutes(float("nan")) == 0

    def test_recorta_valores_absurdos(self):
        # Protege el CHECK de la tabla ante datos corruptos de la fuente.
        assert parse_minutes("9999:00") == 4800

    def test_roundtrip(self):
        assert format_seconds(parse_minutes("34:12")) == "34:12"
        assert format_seconds(0) == "0:00"
        assert format_seconds(parse_minutes("7:05")) == "7:05"


class TestParseGameId:
    @pytest.mark.parametrize(
        ("game_id", "season", "season_type"),
        [
            ("0022300001", "2023-24", SeasonType.REGULAR),
            ("0022400615", "2024-25", SeasonType.REGULAR),
            ("0042300401", "2023-24", SeasonType.PLAYOFFS),
            ("0052300201", "2023-24", SeasonType.PLAYIN),
            ("0012300001", "2023-24", SeasonType.PRESEASON),
            # Años de dos dígitos del siglo pasado.
            ("0029900001", "1999-00", SeasonType.REGULAR),
        ],
    )
    def test_extrae_temporada_y_tipo(self, game_id, season, season_type):
        assert parse_game_id(game_id) == (season, season_type)

    def test_conserva_ceros_a_la_izquierda(self):
        # El motivo por el que game_id es TEXTO y no entero: pasar por int
        # desplaza el código dos posiciones y el partido cambia de identidad.
        # "0022300001" (temporada regular) se leería como All-Star.
        assert parse_game_id("0022300001") == ("2023-24", SeasonType.REGULAR)

        corrompido = str(int("0022300001"))
        assert corrompido == "22300001"
        with pytest.raises(ValueError):
            parse_game_id(corrompido)

    def test_rechaza_all_star(self):
        with pytest.raises(ValueError, match="no soportado"):
            parse_game_id("0032300001")

    def test_rechaza_formato_invalido(self):
        with pytest.raises(ValueError, match="formato inesperado"):
            parse_game_id("abc")


class TestSeasonHelpers:
    @pytest.mark.parametrize(
        ("year", "season_id"),
        [(2023, "2023-24"), (1999, "1999-00"), (2009, "2009-10"), (2025, "2025-26")],
    )
    def test_ida_y_vuelta(self, year, season_id):
        assert season_id_from_start_year(year) == season_id
        assert season_start_year(season_id) == year


class TestLocalGameDate:
    """El cálculo del que dependen todos los splits por día de la semana."""

    def test_partido_nocturno_costa_este_no_salta_de_dia(self):
        # Viernes 5 de enero de 2024, 22:30 en Nueva York.
        tipoff = dt.datetime(2024, 1, 5, 22, 30, tzinfo=ZoneInfo("America/New_York"))
        assert tipoff.astimezone(dt.UTC).date() == dt.date(2024, 1, 6)  # sábado en UTC

        local = local_game_date(tipoff, "America/New_York")
        assert local == dt.date(2024, 1, 5)
        assert local.strftime("%A") == "Friday"

    def test_partido_nocturno_costa_oeste_no_salta_de_dia(self):
        # Viernes 5 de enero de 2024, 19:30 en Los Ángeles = sábado 03:30 UTC.
        tipoff = dt.datetime(2024, 1, 5, 19, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        assert tipoff.astimezone(dt.UTC).date() == dt.date(2024, 1, 6)

        assert local_game_date(tipoff, "America/Los_Angeles") == dt.date(2024, 1, 5)

    def test_acepta_utc_ingenuo(self):
        naive_utc = dt.datetime(2024, 1, 6, 3, 30)
        assert local_game_date(naive_utc, "America/New_York") == dt.date(2024, 1, 5)

    def test_usa_fallback_sin_zona(self):
        fallback = dt.date(2024, 1, 5)
        assert local_game_date(None, None, fallback) == fallback

    def test_sin_zona_cae_a_hora_del_este(self):
        naive_utc = dt.datetime(2024, 1, 6, 3, 30)
        assert local_game_date(naive_utc, None) == dt.date(2024, 1, 5)

    def test_falla_sin_nada(self):
        with pytest.raises(ValueError, match="respaldo"):
            local_game_date(None, None, None)


class TestBiografia:
    """Normalizaciones de los datos biográficos de CommonPlayerInfo."""

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            ("6-4", 193),    # 76 pulgadas
            ("7-2", 218),    # 86 pulgadas — Wembanyama
            ("6-10", 208),
            ("5-3", 160),    # Muggsy Bogues
            (None, None),
            ("", None),
            ("6", None),     # sin guion, formato inesperado
            ("a-b", None),
            ("0-0", None),
        ],
    )
    def test_altura_a_cm(self, valor, esperado):
        assert parse_height_to_cm(valor) == esperado

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            ("225", 102),
            (225, 102),
            ("240", 109),
            ("185", 84),
            (None, None),
            ("", None),
            (" ", None),
            ("no soy un peso", None),
            ("0", None),
            ("-10", None),
        ],
    )
    def test_peso_a_kg(self, valor, esperado):
        assert parse_weight_to_kg(valor) == esperado

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            ("2001-08-05T00:00:00", dt.date(2001, 8, 5)),
            ("1947-04-16 00:00:00", dt.date(1947, 4, 16)),
            ("1984-12-30", dt.date(1984, 12, 30)),
            (None, None),
            ("", None),
            ("no es fecha", None),
        ],
    )
    def test_fecha_nacimiento(self, valor, esperado):
        assert parse_birthdate(valor) == esperado

    def test_altura_es_monotona(self):
        # Comprobación de cordura: más pulgadas, más centímetros.
        alturas = [parse_height_to_cm(f"6-{i}") for i in range(0, 12)]
        assert alturas == sorted(alturas)
        assert parse_height_to_cm("7-0") > parse_height_to_cm("6-11")
