"""Normalizaciones compartidas por toda la ingesta.

Aquí viven los formatos raros de la fuente. La regla es que se normalizan una
sola vez, al entrar; de la base para adentro los tipos ya son limpios.
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from nbastats.db.models import SeasonType

# Primer año de la NBA (1946-47). Sirve de pivote para expandir los años de dos
# dígitos que trae el game_id.
_NBA_FIRST_YEAR = 1946

# Un partido dura 48 min; cada prórroga añade 5. El máximo defendible por
# jugador ronda los 4 OT (48 + 20 = 68 min = 4080 s). El CHECK de la tabla
# permite hasta 4800 s por si acaso.
_MAX_REASONABLE_SECONDS = 4800

_MINUTES_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$")


def parse_minutes(value: str | float | int | None) -> int:
    """Convierte los minutos de la fuente a segundos enteros.

    La NBA los publica en varios formatos y no siempre el mismo dentro de la
    misma respuesta:

        "34:12"        -> 2052   (el habitual)
        "34.000000:12" -> 2052   (quirk conocido de nba_api)
        "34"           -> 2040   (solo minutos)
        34.5           -> 2070   (float, en algunos endpoints)
        "" / None      -> 0      (DNP)

    Devolver 0 en lugar de None para los DNP es deliberado: la fila existe, el
    jugador estuvo disponible y no jugó. Esa diferencia importa al contar
    partidos y al calcular promedios.
    """
    if value is None:
        return 0

    if isinstance(value, (int, float)):
        if value != value or value < 0:  # NaN o negativo
            return 0
        return min(int(round(value * 60)), _MAX_REASONABLE_SECONDS)

    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "-", "null"}:
        return 0

    match = _MINUTES_RE.match(text)
    if match:
        minutes = float(match.group(1))
        seconds = float(match.group(2))
        if minutes < 0:
            return 0
        total = int(round(minutes * 60 + seconds))
        return min(max(total, 0), _MAX_REASONABLE_SECONDS)

    try:
        minutes_only = float(text)
    except ValueError:
        return 0
    if minutes_only < 0:
        return 0
    return min(int(round(minutes_only * 60)), _MAX_REASONABLE_SECONDS)


def format_seconds(seconds: int) -> str:
    """Inverso de parse_minutes, para mostrar en la UI: 2052 -> '34:12'."""
    seconds = max(int(seconds), 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def parse_height_to_cm(value: str | None) -> int | None:
    """Altura en formato imperial de la NBA a centímetros.

        "6-4"  -> 193   (6 pies 4 pulgadas)
        "7-2"  -> 218
        ""     -> None
    """
    if not value:
        return None
    texto = str(value).strip()
    if "-" not in texto:
        return None
    pies, _, pulgadas = texto.partition("-")
    try:
        total_pulgadas = int(pies) * 12 + int(pulgadas)
    except ValueError:
        return None
    if total_pulgadas <= 0:
        return None
    return round(total_pulgadas * 2.54)


def parse_weight_to_kg(value: str | int | None) -> int | None:
    """Peso en libras (como texto o número) a kilogramos."""
    if value in (None, "", " "):
        return None
    try:
        libras = float(str(value).strip())
    except ValueError:
        return None
    if libras <= 0:
        return None
    return round(libras * 0.45359237)


def parse_birthdate(value: str | None) -> dt.date | None:
    """'2001-08-05T00:00:00' -> date(2001, 8, 5)."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def season_id_from_start_year(year: int) -> str:
    """2023 -> '2023-24'."""
    return f"{year}-{(year + 1) % 100:02d}"


def season_start_year(season_id: str) -> int:
    """'2023-24' -> 2023."""
    return int(season_id.split("-")[0])


def parse_game_id(game_id: str) -> tuple[str, SeasonType]:
    """Extrae temporada y tipo de partido del propio game_id.

    El id de la NBA es un código de 10 caracteres con estructura fija:

        0 0 2 23 00001
        │ │ │ │  └── número de partido
        │ │ │ └───── año de inicio de temporada (2 dígitos)
        │ │ └─────── tipo de temporada
        └─┴───────── liga (00 = NBA)

    Se prefiere esto a fiarse de un campo de texto aparte porque el id siempre
    viene y siempre es consistente. Devuelve ('2023-24', SeasonType.REGULAR).
    """
    code = str(game_id).strip()
    if len(code) < 5 or not code[2:5].isdigit():
        raise ValueError(f"game_id con formato inesperado: {game_id!r}")

    type_digit = code[2]
    year_two_digit = int(code[3:5])

    # Pivote: los 2 dígitos son 19xx si caen a partir de 1946, si no 20xx.
    year = (
        1900 + year_two_digit
        if year_two_digit >= _NBA_FIRST_YEAR % 100
        else 2000 + year_two_digit
    )

    season_type = {
        "1": SeasonType.PRESEASON,
        "2": SeasonType.REGULAR,
        "4": SeasonType.PLAYOFFS,
        "5": SeasonType.PLAYIN,
    }.get(type_digit)

    if season_type is None:
        # "3" es el All-Star y "6" la final de la NBA Cup. Ninguno cuenta como
        # partido de temporada para nuestros análisis; el llamador los descarta.
        raise ValueError(f"tipo de partido no soportado en {game_id!r}: '{type_digit}'")

    return season_id_from_start_year(year), season_type


def local_game_date(
    tipoff_utc: dt.datetime | None,
    arena_timezone: str | None,
    fallback: dt.date | None = None,
) -> dt.date:
    """Fecha del partido en la zona horaria del estadio.

    Este es el cálculo del que dependen todos los splits por día de la semana.
    Un partido que empieza el viernes 22:30 en Nueva York son las 03:30 del
    SÁBADO en UTC: derivar el día desde UTC movería de día una fracción
    sistemática de los partidos (los nocturnos, que además son los de mayor
    audiencia) y contaminaría el análisis.
    """
    if tipoff_utc is not None and arena_timezone:
        if tipoff_utc.tzinfo is None:
            tipoff_utc = tipoff_utc.replace(tzinfo=dt.UTC)
        return tipoff_utc.astimezone(ZoneInfo(arena_timezone)).date()

    if fallback is not None:
        return fallback

    if tipoff_utc is not None:
        # Sin zona conocida, la hora del Este es mejor aproximación que UTC:
        # todos los estadios de la NBA están entre ET y PT.
        if tipoff_utc.tzinfo is None:
            tipoff_utc = tipoff_utc.replace(tzinfo=dt.UTC)
        return tipoff_utc.astimezone(ZoneInfo("America/New_York")).date()

    raise ValueError("no hay ni tipoff_utc ni fecha de respaldo")
