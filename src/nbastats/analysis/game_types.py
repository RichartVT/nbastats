"""Traducción de un partido a su tipo legible.

La NBA reparte esta información en tres campos que hay que combinar:

    season_type     regular | playin | playoffs | preseason
    game_label      'Emirates NBA Cup', 'NBA Paris Game', ''
    game_sublabel   'East Group C', 'West Semifinal', ''

**Un partido de la NBA Cup es un partido de temporada regular.** Su
`season_type` es 'regular' y cuenta para la clasificación; solo la final queda
fuera del cómputo. Por eso el tipo mostrable se DERIVA de los tres campos en
vez de existir como una columna: si "NBA Cup" fuera un `season_type`, los 1.230
partidos de temporada regular por año dejarían de cuadrar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Rondas de la NBA Cup, por igualdad de palabra completa.
#
# El `\b` no es decorativo: sin él, "final" casa dentro de "Quarterfinal". Ese
# error exacto ya marcó una vez los 4 cuartos de cada temporada como jugados en
# sede neutral, contradiciendo el `isNeutral=False` que devuelve la propia API.
_RONDA_CUP = (
    (re.compile(r"\bgroup\b", re.IGNORECASE), "Grupo"),
    (re.compile(r"\bquarterfinal\b", re.IGNORECASE), "Cuartos"),
    (re.compile(r"\bsemifinal\b", re.IGNORECASE), "Semifinal"),
    (re.compile(r"\bchampionship\b", re.IGNORECASE), "Final"),
)

# Etiqueta de partido internacional: "NBA Paris Game" -> "París".
_CIUDADES = {
    "paris": "París",
    "mexico city": "Ciudad de México",
    "london": "Londres",
    "berlin": "Berlín",
    "abu dhabi": "Abu Dabi",
    "tokyo": "Tokio",
    "macau": "Macao",
    "shanghai": "Shanghái",
    "beijing": "Pekín",
    "vancouver": "Vancouver",
    "montreal": "Montreal",
}


@dataclass(frozen=True)
class GameType:
    key: str
    """Identificador estable para el frontend: 'regular', 'cup', 'playoffs'…"""

    label: str
    """Texto corto para la insignia: 'NBA Cup · Grupo'."""

    is_postseason: bool


REGULAR = GameType("regular", "Temporada regular", False)


def describe_game(
    season_type: str,
    game_label: str | None = None,
    game_sublabel: str | None = None,
) -> GameType:
    """Devuelve el tipo mostrable de un partido.

    >>> describe_game("regular").label
    'Temporada regular'
    >>> describe_game("regular", "Emirates NBA Cup", "East Group C").label
    'NBA Cup · Grupo'
    >>> describe_game("playoffs").label
    'Playoffs'
    """
    if season_type == "playoffs":
        return GameType("playoffs", "Playoffs", True)
    if season_type == "playin":
        return GameType("playin", "Play-In", True)
    if season_type == "preseason":
        return GameType("preseason", "Pretemporada", False)

    etiqueta = (game_label or "").strip()
    if not etiqueta:
        return REGULAR

    if "cup" in etiqueta.lower():
        for patron, ronda in _RONDA_CUP:
            if patron.search(game_sublabel or ""):
                return GameType("cup", f"NBA Cup · {ronda}", False)
        return GameType("cup", "NBA Cup", False)

    minusculas = etiqueta.lower()
    for clave, ciudad in _CIUDADES.items():
        if clave in minusculas:
            return GameType("international", ciudad, False)

    # Etiqueta desconocida: se muestra tal cual en vez de tragarla. Si la NBA
    # inventa un formato nuevo, preferimos verlo en pantalla a que desaparezca.
    return GameType("labeled", etiqueta[:40], False)
