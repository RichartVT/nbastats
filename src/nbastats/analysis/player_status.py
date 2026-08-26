"""Situación actual de un jugador: en plantilla, sin equipo o fuera de la liga.

La NBA no publica un campo "estado del jugador". Publica `rosterStatus`, que
solo tiene dos valores —Active / Inactive— y que responde a una pregunta muy
concreta: *¿pertenece hoy a una plantilla?* Eso deja fuera casi todo lo que
alguien quiere saber al mirar una lista de jugadores.

El estado mostrable se DERIVA de tres cosas que sí tenemos:

    roster_status        Active / Inactive, tal cual lo da la NBA
    last_season_played   última temporada con partidos en nuestros datos
    latest_season        la temporada más reciente cargada

Cruzarlas separa cuatro situaciones que `rosterStatus` mete en el mismo saco:

    Active   + jugó la última temporada  -> en plantilla, jugando
    Active   + no jugó la última         -> en plantilla, sin minutos
    Inactive + jugó la última temporada  -> se quedó sin equipo hace poco
    Inactive + no juega desde antes      -> lleva al menos una temporada fuera

LO QUE NO SE AFIRMA, Y POR QUÉ. Nunca se etiqueta a nadie de "retirado". El
dato que tenemos es "no aparece en ninguna plantilla NBA y no juega desde
2022-23"; eso lo cumple igual quien colgó las zapatillas que quien está jugando
en la Euroliga o en la G-League. Como no hay ningún campo que distinga los dos
casos, la etiqueta dice lo que sabemos —"Fuera de la liga"— y la nota deja
constancia de lo que no. Poner "Retirado" sería inventarse el motivo.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlayerStatus:
    key: str
    """Identificador estable para el frontend: 'activo', 'agente_libre'…"""

    label: str
    """Texto corto para la insignia: 'Activo', 'Fuera de la liga'."""

    note: str
    """Una línea explicando qué significa, con las fechas concretas."""

    on_roster: bool
    """¿Pertenece hoy a una plantilla de la NBA?"""

    @property
    def team_label(self) -> str:
        """Cómo llamar a su equipo. Para quien no está en plantilla, el equipo
        que traemos es el ÚLTIMO en el que estuvo, no el actual: enseñarlo como
        "equipo actual" sería falso."""
        return "Equipo actual" if self.on_roster else "Último equipo"


def describe_status(
    roster_status: str | None,
    last_season_played: str | None,
    latest_season: str,
    team_name: str | None = None,
) -> PlayerStatus:
    """Traduce el estado crudo de la NBA al estado mostrable.

    >>> describe_status("Active", "2025-26", "2025-26", "Denver Nuggets").label
    'Activo'
    >>> describe_status("Inactive", "2025-26", "2025-26").label
    'Agente libre'
    >>> describe_status("Inactive", "2022-23", "2025-26").label
    'Fuera de la liga'
    >>> describe_status("Inactive", None, "2025-26").key
    'sin_datos'
    """
    en_curso = last_season_played == latest_season

    if roster_status == "Active":
        if en_curso:
            nota = (
                f"En la plantilla de {team_name}." if team_name else "En una plantilla NBA."
            )
        else:
            # Existe: 6 jugadores con ficha y sin un solo partido en la última
            # temporada. Lesión de larga duración, contrato dual o final de
            # banquillo. Enseñarlos como "Activo" a secas y con 0 partidos
            # parece un fallo de datos; la nota explica que no lo es.
            nota = (
                f"En la plantilla de {team_name}, pero sin"
                if team_name
                else "En una plantilla NBA, pero sin"
            ) + f" partidos en {latest_season}."
        return PlayerStatus("activo", "Activo", nota, on_roster=True)

    if last_season_played is None:
        return PlayerStatus(
            "sin_datos",
            "Sin partidos",
            "No tiene partidos en las temporadas cargadas.",
            on_roster=False,
        )

    if en_curso:
        return PlayerStatus(
            "agente_libre",
            "Agente libre",
            f"Jugó en {latest_season} y no figura en ninguna plantilla"
            f"{f'. Su último equipo fue {team_name}' if team_name else ''}.",
            on_roster=False,
        )

    return PlayerStatus(
        "fuera_liga",
        "Fuera de la liga",
        f"Sin partidos NBA desde {last_season_played}. Puede estar retirado o "
        "jugando fuera de la NBA: el dato de la liga no distingue los dos casos"
        f"{f'. Su último equipo fue {team_name}' if team_name else ''}.",
        on_roster=False,
    )
