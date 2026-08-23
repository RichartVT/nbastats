"""Endpoints de equipo: ficha, historial, clasificación, enfrentamientos y análisis.

El análisis de equipo reutiliza `analyze_trend` y `analyze_splits` sin
modificarlos: esos módulos reciben listas de números y son indiferentes a si
vienen de un jugador o de una franquicia. Es la ventaja de haberlos escrito
sobre datos y no sobre entidades.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from nbastats.analysis.game_types import describe_game
from nbastats.analysis.reliability import analyze_splits
from nbastats.analysis.trends import analyze_trend, rolling_mean
from nbastats.api import team_queries as tq
from nbastats.api.catalog import DIMENSIONS, Dimension
from nbastats.api.schemas import (
    GameTypeOut,
    HeadToHeadOut,
    RosterEntryOut,
    SplitOut,
    StandingOut,
    TeamGameOut,
    TeamOut,
    TeamSummaryOut,
)
from nbastats.db.session import get_db

router = APIRouter(tags=["equipos"])

SeasonQuery = Query(None, description="Temporada, ej. 2024-25. Vacío = la más reciente")


def _game_type(fila: dict) -> GameTypeOut:
    t = describe_game(
        fila.get("season_type", "regular"),
        fila.get("game_label"),
        fila.get("game_sublabel"),
    )
    return GameTypeOut(key=t.key, label=t.label, is_postseason=t.is_postseason)


def _to_team_game(fila: dict) -> TeamGameOut:
    return TeamGameOut(game_type=_game_type(fila), **{
        k: v for k, v in fila.items()
        if k in TeamGameOut.model_fields and k != "game_type"
    })


@router.get("/teams", response_model=list[TeamSummaryOut])
def list_teams(
    season: str | None = SeasonQuery, db: Session = Depends(get_db)
) -> list[TeamSummaryOut]:
    return [TeamSummaryOut(**f) for f in tq.list_teams(db, season)]


@router.get("/teams/{team_id}", response_model=TeamOut)
def get_team(
    team_id: int, season: str | None = SeasonQuery, db: Session = Depends(get_db)
) -> TeamOut:
    datos = tq.get_team(db, team_id, season)
    if not datos:
        raise HTTPException(404, f"No existe el equipo {team_id}")

    plantilla = [RosterEntryOut(**f) for f in tq.get_roster(db, team_id, season)]
    campos = {k: v for k, v in datos.items() if k in TeamOut.model_fields}
    campos["season_id"] = datos.get("standings_season")
    return TeamOut(**campos, roster=plantilla)


@router.get("/teams/{team_id}/games", response_model=list[TeamGameOut])
def get_team_games(
    team_id: int,
    seasons: list[str] | None = Query(None),
    limit: int | None = Query(None, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[TeamGameOut]:
    """Historial de partidos, del más reciente al más antiguo.

    Incluye playoffs y play-in: el calendario de un equipo es su temporada
    entera, no solo la fase regular.
    """
    return [_to_team_game(f) for f in tq.get_team_games(db, team_id, seasons, limit=limit)]


@router.get("/teams/{team_id}/roster", response_model=list[RosterEntryOut])
def get_roster(
    team_id: int, season: str | None = SeasonQuery, db: Session = Depends(get_db)
) -> list[RosterEntryOut]:
    return [RosterEntryOut(**f) for f in tq.get_roster(db, team_id, season)]


@router.get("/standings", response_model=list[StandingOut], tags=["clasificación"])
def get_standings(
    season: str | None = SeasonQuery, db: Session = Depends(get_db)
) -> list[StandingOut]:
    """Clasificación oficial, con los desempates de la NBA ya aplicados."""
    return [
        StandingOut(**{k: v for k, v in f.items() if k in StandingOut.model_fields})
        for f in tq.get_standings(db, season)
    ]


@router.get("/teams/{team_a}/vs/{team_b}", response_model=HeadToHeadOut)
def head_to_head(
    team_a: int,
    team_b: int,
    seasons: list[str] | None = Query(None),
    db: Session = Depends(get_db),
) -> HeadToHeadOut:
    """Enfrentamientos directos entre dos equipos."""
    a = tq.get_team(db, team_a)
    b = tq.get_team(db, team_b)
    if not a or not b:
        raise HTTPException(404, "Alguno de los dos equipos no existe")
    if team_a == team_b:
        raise HTTPException(400, "Un equipo no juega contra sí mismo")

    partidos = tq.get_head_to_head(db, team_a, team_b, seasons)
    victorias_a = sum(1 for p in partidos if p["won"])
    diffs = [p["point_diff"] for p in partidos if p["point_diff"] is not None]

    def resumen(datos: dict) -> TeamSummaryOut:
        return TeamSummaryOut(
            **{k: v for k, v in datos.items() if k in TeamSummaryOut.model_fields}
        )

    return HeadToHeadOut(
        team_a=resumen(a),
        team_b=resumen(b),
        seasons=sorted({p["season_id"] for p in partidos}),
        games_played=len(partidos),
        team_a_wins=victorias_a,
        team_b_wins=len(partidos) - victorias_a,
        avg_point_diff=round(sum(diffs) / len(diffs), 2) if diffs else None,
        games=[_to_team_game(p) for p in partidos],
    )


# =========================================================================
# Análisis de equipo
# =========================================================================


@router.get("/teams/{team_id}/trend", tags=["análisis"])
def team_trend(
    team_id: int,
    stat: str = Query("net_rating"),
    window: int = Query(15, ge=5, le=82),
    seasons: list[str] | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Tendencia de un equipo: ¿mejorando, empeorando o estable?

    La ventana por defecto es de 15 partidos y no de 25 como en jugadores: un
    equipo cambia de identidad con un traspaso o una lesión, así que una
    ventana larga suaviza justo lo que interesa ver.
    """
    if stat not in tq.TEAM_STATS:
        raise HTTPException(400, f"Estadística no válida: {stat}")

    equipo = tq.get_team(db, team_id)
    if not equipo:
        raise HTTPException(404, f"No existe el equipo {team_id}")

    valores, fechas = tq.get_team_series(db, team_id, stat, seasons)
    r = analyze_trend(valores)
    suave = rolling_mean(valores, window) if valores else []

    def limpio(x: float) -> float | None:
        return None if x != x else round(x, 4)

    return {
        "team_id": team_id,
        "team_name": equipo["full_name"],
        "stat": stat,
        "stat_label": tq.TEAM_STATS[stat][1],
        "n": r.n,
        "direction": r.direction.value,
        "reliability": r.reliability.value,
        "slope_per_season": limpio(r.slope_per_season),
        "ci95_low": limpio(r.slope_ci95[0] * 82),
        "ci95_high": limpio(r.slope_ci95[1] * 82),
        "r_squared": limpio(r.r_squared),
        "mk_p_value": limpio(r.mk_p_value),
        "tau": limpio(r.tau),
        "change_points": r.change_points,
        "note": r.note,
        "series": [round(v, 4) for v in valores],
        "rolling": [None if v is None else round(v, 4) for v in suave],
        "dates": [f.isoformat() for f in fechas],
    }


@router.get("/teams/{team_id}/splits", tags=["análisis"])
def team_splits(
    team_id: int,
    dimension: Dimension = Query(Dimension.HOME_AWAY),
    stat: str = Query("net_rating"),
    seasons: list[str] | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Rendimiento de un equipo partido por una dimensión, con incertidumbre.

    Misma garantía que en jugadores: nunca un número solo. Cada nivel viaja con
    su tamaño de muestra, intervalo y valor q corregido por FDR.
    """
    if stat not in tq.TEAM_STATS:
        raise HTTPException(400, f"Estadística no válida: {stat}")

    equipo = tq.get_team(db, team_id)
    if not equipo:
        raise HTTPException(404, f"No existe el equipo {team_id}")

    grupos = tq.get_team_split_groups(db, team_id, stat, dimension, seasons)
    salida = [SplitOut.from_estimate(e) for e in analyze_splits(grupos).values()]

    aviso = DIMENSIONS[dimension].warning
    if not any(s.distinguishable for s in salida):
        aviso = (
            "Ningún nivel se distingue del resto tras corregir por comparaciones "
            "múltiples: aquí no hay patrón, solo variación normal. "
        ) + aviso

    return {
        "team_id": team_id,
        "team_name": equipo["full_name"],
        "stat": stat,
        "stat_label": tq.TEAM_STATS[stat][1],
        "dimension": dimension.value,
        "dimension_label": DIMENSIONS[dimension].label,
        "total_games": sum(len(v) for v in grupos.values()),
        "splits": [s.model_dump() for s in salida],
        "caveat": aviso,
        "any_distinguishable": any(s.distinguishable for s in salida),
    }


@router.get("/team-catalog", tags=["meta"])
def team_catalog() -> dict:
    """Estadísticas de equipo consultables."""
    return {
        "stats": [
            {"value": clave, "label": etiqueta}
            for clave, (_, etiqueta) in tq.TEAM_STATS.items()
        ]
    }
