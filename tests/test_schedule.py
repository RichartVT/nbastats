"""El parseo del calendario.

POR QUÉ HAY QUE PROBARLO APARTE. Es la primera ingesta del proyecto que trata
con partidos que todavía no existen, y ahí la fuente usa convenciones que no
aparecen en ningún otro endpoint: un equipo «cero» para decir «por determinar»
y un año cero para decir «la hora aún no está fijada». Las dos parecen datos
válidos y ninguna lo es.
"""

from __future__ import annotations

import datetime as dt

import pytest

from nbastats.db.models import SeasonType
from nbastats.ingest.schedule import parse_schedule

# Ids reales de equipo: los Lakers y los Celtics.
LAL = 1610612747
BOS = 1610612738


def juego(**kw):
    """Un partido del calendario, con los valores por defecto de la fuente."""
    base = {
        "gameId": "0022600002",
        "gameStatus": 1,
        "gameDateEst": "2026-10-20T00:00:00Z",
        "gameTimeEst": "1900-01-01T19:00:00Z",
        "gameDateTimeUTC": "2026-10-20T23:00:00Z",
        "weekNumber": 1,
        "gameLabel": "",
        "gameSubLabel": "",
        "arenaName": "TD Garden",
        "arenaCity": "Boston",
        "postponedStatus": "N",
        "isNeutral": False,
        "homeTeam": {"teamId": BOS},
        "awayTeam": {"teamId": LAL},
    }
    return base | kw


def calendario(*juegos, season="2026-27"):
    return {"seasonYear": season, "gameDates": [{"games": list(juegos)}]}


class TestPartidoNormal:
    def test_se_parsea_entero(self):
        (fila,) = parse_schedule(calendario(juego()))

        assert fila["game_id"] == "0022600002"
        assert fila["season_id"] == "2026-27"
        assert fila["season_type"] is SeasonType.REGULAR
        assert fila["home_team_id"] == BOS
        assert fila["away_team_id"] == LAL
        assert fila["arena_name"] == "TD Garden"
        assert fila["week_number"] == 1
        assert fila["is_neutral_site"] is False

    def test_la_temporada_sale_de_la_cabecera_no_del_id(self):
        """La cabecera es una fuente menos por la que equivocarse."""
        (fila,) = parse_schedule(calendario(juego(), season="2026-27"))
        assert fila["season_id"] == "2026-27"

    def test_las_etiquetas_vacias_son_NULL_no_cadena_vacia(self):
        """Un partido normal NO lleva etiqueta, y eso se escribe NULL."""
        (fila,) = parse_schedule(calendario(juego()))
        assert fila["game_label"] is None
        assert fila["game_sublabel"] is None

    def test_la_etiqueta_se_conserva_cuando_la_hay(self):
        (fila,) = parse_schedule(
            calendario(juego(gameLabel="Emirates NBA Cup", gameSubLabel="West Group A"))
        )
        assert fila["game_label"] == "Emirates NBA Cup"
        assert fila["game_sublabel"] == "West Group A"

    def test_la_sede_neutral_se_toma_de_la_fuente(self):
        """En este endpoint `isNeutral` viene poblado: no hace falta heurística."""
        (fila,) = parse_schedule(
            calendario(juego(isNeutral=True, gameLabel="NBA Paris Game"))
        )
        assert fila["is_neutral_site"] is True


class TestFechaLocal:
    def test_un_partido_nocturno_no_se_va_al_dia_siguiente(self):
        """El cálculo del que dependen todos los splits por día de la semana.

        Un partido en Los Ángeles a las 19:30 del martes son las 02:30 del
        MIÉRCOLES en UTC. Derivar la fecha desde UTC lo movería de día.
        """
        (fila,) = parse_schedule(
            calendario(
                juego(
                    homeTeam={"teamId": LAL},
                    awayTeam={"teamId": BOS},
                    gameDateEst="2026-11-10T00:00:00Z",
                    gameDateTimeUTC="2026-11-11T03:30:00Z",
                )
            )
        )
        assert fila["game_date_local"] == dt.date(2026, 11, 10)

    def test_sin_local_se_usa_la_fecha_que_publica_la_nba(self):
        """Sin equipo local no hay zona horaria de estadio con la que derivarla."""
        (fila,) = parse_schedule(
            calendario(
                juego(
                    homeTeam={"teamId": 0},
                    awayTeam={"teamId": 0},
                    gameDateEst="2026-12-04T00:00:00Z",
                )
            )
        )
        assert fila["game_date_local"] == dt.date(2026, 12, 4)


class TestPorDeterminar:
    """Los cruces de la NBA Cup: se publican en agosto sin contendientes."""

    def test_el_equipo_cero_es_un_hueco_no_un_equipo(self):
        """`teamId: 0` guardado tal cual violaría la clave ajena contra `teams`."""
        (fila,) = parse_schedule(
            calendario(juego(homeTeam={"teamId": 0}, awayTeam={"teamId": 0}))
        )
        assert fila["home_team_id"] is None
        assert fila["away_team_id"] is None

    def test_el_partido_se_guarda_igual(self):
        """Sin rival sigue siendo una fecha del calendario que la gente mira."""
        filas = parse_schedule(
            calendario(
                juego(
                    gameId="0022601201",
                    gameLabel="Emirates NBA Cup",
                    gameSubLabel="Quarterfinal",
                    homeTeam={"teamId": 0},
                    awayTeam={"teamId": 0},
                )
            )
        )
        assert len(filas) == 1
        assert filas[0]["game_sublabel"] == "Quarterfinal"

    def test_la_hora_sin_fijar_no_se_inventa(self):
        """El bug que motivó este test.

        Cuando la hora no está decidida, la fuente manda `gameTimeEst` con el
        año 0001 y un `gameDateTimeUTC` que sale como medianoche del Este. Eso
        PARECE una hora de salto inicial —las 05:00 UTC— y no lo es: guardarla
        pondría todos los cruces de la Cup a la una de la madrugada.
        """
        (fila,) = parse_schedule(
            calendario(
                juego(
                    gameTimeEst="0001-01-01T00:00:00Z",
                    gameDateEst="2026-12-04T00:00:00Z",
                    gameDateTimeUTC="2026-12-04T05:00:00Z",
                    homeTeam={"teamId": 0},
                    awayTeam={"teamId": 0},
                )
            )
        )
        assert fila["tipoff_utc"] is None
        assert fila["game_date_local"] == dt.date(2026, 12, 4)

    def test_la_hora_normal_si_se_guarda(self):
        (fila,) = parse_schedule(calendario(juego()))
        assert fila["tipoff_utc"] == dt.datetime(2026, 10, 20, 23, 0, tzinfo=dt.UTC)


class TestQueNoEntra:
    def test_la_pretemporada_se_descarta(self):
        """Se filtra al ENTRAR, no al consultar.

        Filtrarla en la vista la deja volver por cualquier consulta nueva que
        se escriba después.
        """
        assert parse_schedule(calendario(juego(gameId="0012600009"))) == []

    @pytest.mark.parametrize(
        ("game_id", "etiqueta"),
        [
            ("0032500011", "All-Star"),
            ("0032500004", "Rising Stars Semifinal"),
            ("0032500041", "All-Star Championship"),
        ],
    )
    def test_el_fin_de_semana_del_all_star_se_descarta(self, game_id, etiqueta):
        """El bug que motivó este test.

        Lo juegan equipos montados para la ocasión, con ids propios
        (1610616859 y siguientes) que NO existen en `teams`. Guardarlos viola
        la clave ajena y tira la ingesta de la temporada entera: en 2025-26
        son 7 partidos capaces de impedir que entren los otros 1.322.
        """
        assert (
            parse_schedule(
                calendario(
                    juego(
                        gameId=game_id,
                        gameLabel=etiqueta,
                        homeTeam={"teamId": 1610616859},
                        awayTeam={"teamId": 1610616861},
                    )
                )
            )
            == []
        )

    def test_un_partido_sin_id_no_rompe_el_resto(self):
        filas = parse_schedule(calendario(juego(gameId=""), juego()))
        assert [f["game_id"] for f in filas] == ["0022600002"]


class TestFinalDeLaCup:
    """Tipo '6': ni temporada regular, ni playoffs, ni play-in."""

    def test_entra_con_el_tipo_sin_resolver(self):
        """`parse_game_id` levanta ValueError con el tipo '6'.

        En los análisis eso es correcto —la final de la Cup no cuenta para la
        temporada— pero en el CALENDARIO el partido se juega y la gente lo
        busca. El error se traduce a «sin fase» en vez de tirar las otras 1.206
        filas.
        """
        (fila,) = parse_schedule(
            calendario(
                juego(
                    gameId="0062600001",
                    gameLabel="Emirates NBA Cup",
                    gameSubLabel="Championship",
                    isNeutral=True,
                )
            )
        )
        assert fila["season_type"] is None
        assert fila["game_sublabel"] == "Championship"


def test_un_calendario_sin_temporada_es_un_error():
    """Sin `seasonYear` no hay a qué temporada atribuir los partidos."""
    with pytest.raises(ValueError, match="seasonYear"):
        parse_schedule({"gameDates": [{"games": [juego()]}]})


def test_un_calendario_vacio_no_es_un_error():
    """La NBA publica en agosto: antes, el endpoint responde sin partidos."""
    assert parse_schedule({"seasonYear": "2027-28", "gameDates": []}) == []
