"""Traducción de un partido a su tipo legible.

La NBA reparte esta información en tres campos que hay que combinar:

    season_type     regular | playin | playoffs | preseason
    game_label      'Emirates NBA Cup', 'NBA Finals', 'West First Round', ''
    game_sublabel   'East Group C', 'West Semifinal', ''

**Un partido de la NBA Cup es un partido de temporada regular.** Su
`season_type` es 'regular' y cuenta para la clasificación; solo la final queda
fuera. Por eso el tipo mostrable se DERIVA de los tres campos en vez de existir
como columna: si "NBA Cup" fuera un `season_type`, los 1.230 partidos de
temporada regular por año dejarían de cuadrar.

DOS COSAS QUE SOLO SE VIERON CON LOS DATOS CARGADOS:

1. Las etiquetas de playoffs traen la RONDA ('NBA Finals', 'West First Round'),
   no solo el hecho de ser playoffs. Devolver un genérico "Playoffs" tiraba la
   parte informativa: en un historial, saber que un partido fue de Finales o de
   primera ronda es justo lo que se quiere leer.

2. El formato cambia entre temporadas. Hasta 2023-24 se escribía
   'East - Conf. Finals' y desde 2024-25 'East Conf. Finals', sin guion. Y las
   etiquetas llevan patrocinador ('SoFi Play-In Tournament', 'Emirates NBA
   Cup', 'AWS NBA Rivals Week'), que cambia cada año. Por eso el emparejamiento
   busca la parte con significado y nunca el nombre del patrocinador.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Rondas de la NBA Cup, por palabra completa.
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

# Rondas de playoffs. El orden importa: "Conf. Semifinals" contiene "Finals",
# así que las semifinales tienen que probarse ANTES que las finales.
_RONDA_PLAYOFF = (
    (re.compile(r"\bfirst\s+round\b", re.IGNORECASE), "Primera ronda"),
    (re.compile(r"\bsemifinals?\b", re.IGNORECASE), "Semifinales"),
    (re.compile(r"\bnba\s+finals?\b", re.IGNORECASE), "Finales NBA"),
    (re.compile(r"\bfinals?\b", re.IGNORECASE), "Final de conferencia"),
)

# En playoffs, el sublabel trae el número de partido de la eliminatoria
# ("Game 7"). Es información valiosa en un historial: no es lo mismo un primer
# partido que un séptimo.
_NUMERO_PARTIDO = re.compile(r"\bgame\s+(\d+)\b", re.IGNORECASE)

_CONFERENCIA = (
    (re.compile(r"\beast\b", re.IGNORECASE), "Este"),
    (re.compile(r"\bwest\b", re.IGNORECASE), "Oeste"),
)

# Los partidos internacionales llevan la ciudad en la etiqueta. Se busca la
# ciudad y no la palabra "NBA", que aparece en casi todas.
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

# Patrocinadores que preceden al nombre real del evento y cambian cada año.
_PATROCINADORES = re.compile(
    r"^(emirates|sofi|aws|at&t|kia|state\s*farm|michelob\s*ultra)\s+", re.IGNORECASE
)


@dataclass(frozen=True)
class GameType:
    key: str
    """Identificador estable para el frontend: 'regular', 'cup', 'playoffs'…"""

    label: str
    """Texto corto para la insignia: 'NBA Cup · Grupo', 'Finales NBA'."""

    is_postseason: bool


REGULAR = GameType("regular", "Temporada regular", False)


def _sin_patrocinador(etiqueta: str) -> str:
    return _PATROCINADORES.sub("", etiqueta).strip()


def _conferencia(texto: str) -> str | None:
    for patron, nombre in _CONFERENCIA:
        if patron.search(texto):
            return nombre
    return None


def _ronda_playoff(etiqueta: str) -> str:
    """Traduce 'West Conf. Semifinals' a 'Semifinales Oeste'."""
    for patron, nombre in _RONDA_PLAYOFF:
        if patron.search(etiqueta):
            # Las Finales NBA no son de conferencia; el resto sí.
            if nombre == "Finales NBA":
                return nombre
            conf = _conferencia(etiqueta)
            return f"{nombre} {conf}" if conf else nombre
    return "Playoffs"


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
    >>> describe_game("playoffs", "NBA Finals").label
    'Finales NBA'
    >>> describe_game("playoffs", "West - Conf. Semifinals").label
    'Semifinales Oeste'
    >>> describe_game("playoffs", "NBA Finals", "Game 7").label
    'Finales NBA · G7'
    """
    etiqueta = _sin_patrocinador((game_label or "").strip())

    if season_type == "playoffs":
        ronda = _ronda_playoff(etiqueta) if etiqueta else "Playoffs"
        partido = _NUMERO_PARTIDO.search(game_sublabel or "")
        if partido:
            ronda = f"{ronda} · G{partido.group(1)}"
        return GameType("playoffs", ronda, True)

    if season_type == "playin":
        conf = _conferencia(etiqueta)
        return GameType("playin", f"Play-In {conf}" if conf else "Play-In", True)

    if season_type == "preseason":
        return GameType("preseason", "Pretemporada", False)

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

    # Etiqueta desconocida —"NBA Rivals Week", "NBA Pioneers Classic"— se
    # muestra tal cual. Si la NBA inventa un evento nuevo, preferimos verlo en
    # pantalla a que desaparezca sin dejar rastro.
    return GameType("labeled", etiqueta[:40], False)
