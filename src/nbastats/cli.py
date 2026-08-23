"""Interfaz de línea de comandos.

    uv run nbastats status                # qué hay cargado
    uv run nbastats setup                 # migraciones + vistas
    uv run nbastats ingest-seasons        # carga histórica completa
    uv run nbastats ingest-bios           # biografías (fechas de nacimiento)
    uv run nbastats enrich                # hora de inicio + sedes neutrales
    uv run nbastats daily                 # actualización diaria
    uv run nbastats refresh               # recalcula derivadas y vistas
"""

from __future__ import annotations

import datetime as dt
import logging

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

import nbastats.db.models as m
from nbastats.config import get_settings
from nbastats.db.session import session_scope
from nbastats.ingest.transforms import season_id_from_start_year

app = typer.Typer(add_completion=False, help="Estadísticas NBA: ingesta y mantenimiento.")
console = Console()

# La temporada de la NBA arranca en octubre. Antes de octubre, la temporada
# "actual" sigue siendo la que empezó el año pasado.
_MES_INICIO_TEMPORADA = 10


def _configurar_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )


def temporada_actual(hoy: dt.date | None = None) -> str:
    hoy = hoy or dt.date.today()
    inicio = hoy.year if hoy.month >= _MES_INICIO_TEMPORADA else hoy.year - 1
    return season_id_from_start_year(inicio)


@app.command()
def status() -> None:
    """Muestra qué hay cargado en la base."""
    with session_scope() as s:
        tabla = Table(title="Estado de la base", header_style="bold")
        tabla.add_column("Tabla")
        tabla.add_column("Filas", justify="right")

        for modelo in (m.Team, m.Player, m.Season, m.Game, m.TeamGameStats,
                       m.PlayerGameStats, m.PlayerGameAdvanced):
            n = s.scalar(select(func.count()).select_from(modelo))
            tabla.add_row(modelo.__tablename__, f"{n:,}")
        console.print(tabla)

        # Cobertura de los datos que habilitan análisis concretos.
        total_jug = s.scalar(select(func.count()).select_from(m.Player))
        con_fecha = s.scalar(
            select(func.count()).select_from(m.Player).where(m.Player.birthdate.isnot(None))
        )
        total_part = s.scalar(select(func.count()).select_from(m.Game))
        con_hora = s.scalar(
            select(func.count()).select_from(m.Game).where(m.Game.tipoff_utc.isnot(None))
        )
        neutrales = s.scalar(
            select(func.count()).select_from(m.Game).where(m.Game.is_neutral_site)
        )

        cob = Table(title="Cobertura", header_style="bold")
        cob.add_column("Dato")
        cob.add_column("Cobertura", justify="right")
        cob.add_column("Habilita")
        cob.add_row(
            "Fecha de nacimiento",
            f"{con_fecha:,}/{total_jug:,}" if total_jug else "—",
            "curvas de edad",
        )
        cob.add_row(
            "Hora de inicio",
            f"{con_hora:,}/{total_part:,}" if total_part else "—",
            "splits por horario",
        )
        cob.add_row("Sedes neutrales", f"{neutrales:,}", "split local/visitante limpio")
        console.print(cob)

        temporadas = s.execute(
            select(m.Game.season_id, m.Game.season_type, func.count())
            .group_by(m.Game.season_id, m.Game.season_type)
            .order_by(m.Game.season_id, m.Game.season_type)
        ).all()
        if temporadas:
            t = Table(title="Partidos por temporada", header_style="bold")
            t.add_column("Temporada")
            t.add_column("Tipo")
            t.add_column("Partidos", justify="right")
            for season_id, season_type, n in temporadas:
                t.add_row(season_id, season_type.value, f"{n:,}")
            console.print(t)


@app.command()
def setup(verbose: bool = False) -> None:
    """Aplica migraciones y (re)crea las vistas materializadas."""
    _configurar_logging(verbose)
    import subprocess

    console.print("[bold]Aplicando migraciones...[/bold]")
    subprocess.run(["alembic", "upgrade", "head"], check=True)

    from nbastats.db.maintenance import rebuild_views

    console.print("[bold]Recreando vistas...[/bold]")
    rebuild_views()
    console.print("[green]Listo.[/green]")


@app.command("ingest-seasons")
def ingest_seasons_cmd(
    seasons: str = typer.Option("", help="Coma-separadas. Vacío = las del .env"),
    verbose: bool = False,
) -> None:
    """Carga histórica: box scores de jugador y equipo."""
    _configurar_logging(verbose)
    from nbastats.ingest.bulk import ingest_seasons

    lista = [x.strip() for x in seasons.split(",") if x.strip()] or get_settings().season_list
    console.print(f"[bold]Cargando:[/bold] {', '.join(lista)}")

    res = ingest_seasons(lista)
    console.print(
        f"[green]{sum(r.games for r in res):,} partidos, "
        f"{sum(r.player_rows for r in res):,} filas jugador[/green]"
    )
    descartados = [x for r in res for x in r.skipped]
    if descartados:
        console.print(f"[yellow]{len(descartados)} descartados:[/yellow] {descartados[:5]}")


@app.command("ingest-bios")
def ingest_bios_cmd(
    all_players: bool = typer.Option(False, "--all", help="Refrescar también las ya cargadas"),
    verbose: bool = False,
) -> None:
    """Biografías: fecha de nacimiento, altura, peso, posición."""
    _configurar_logging(verbose)
    from nbastats.ingest.bio import ingest_player_bios

    r = ingest_player_bios(only_missing=not all_players)
    console.print(f"[green]{r['actualizados']:,} actualizadas, {r['fallidos']} fallidas[/green]")


@app.command()
def enrich(
    all_games: bool = typer.Option(False, "--all", help="Reprocesar todas las fechas"),
    verbose: bool = False,
) -> None:
    """Hora de inicio y detección de sedes neutrales (una petición por fecha)."""
    _configurar_logging(verbose)
    from nbastats.ingest.enrich import enrich_games

    r = enrich_games(only_missing=not all_games)
    console.print(
        f"[green]{r['partidos']:,} partidos actualizados, "
        f"{r['neutrales']} en sede neutral[/green]"
    )


@app.command()
def refresh(verbose: bool = False) -> None:
    """Recalcula columnas derivadas y refresca las vistas materializadas."""
    _configurar_logging(verbose)
    from nbastats.db.maintenance import compute_derived_columns, refresh_views

    filas = compute_derived_columns()
    refresh_views()
    console.print(f"[green]{filas:,} filas derivadas, vistas refrescadas[/green]")


@app.command()
def daily(verbose: bool = False) -> None:
    """Actualización diaria.

    Recarga la temporada ACTUAL entera en lugar de calcular un rango de fechas.
    Puede parecer excesivo, pero `PlayerGameLogs` devuelve la temporada completa
    en ~1 segundo, así que son 4 peticiones: más simple que cualquier lógica
    incremental, y recoge gratis las correcciones oficiales de box scores que la
    NBA publica días después de cada partido.
    """
    _configurar_logging(verbose)
    from nbastats.db.maintenance import compute_derived_columns, refresh_views
    from nbastats.ingest.bio import ingest_player_bios
    from nbastats.ingest.bulk import ingest_seasons
    from nbastats.ingest.enrich import enrich_games

    season = temporada_actual()
    console.print(f"[bold]Temporada actual: {season}[/bold]")

    res = ingest_seasons([season])
    console.print(f"  {sum(r.games for r in res):,} partidos")

    enriquecido = enrich_games(only_missing=True)
    console.print(f"  {enriquecido['partidos']:,} partidos enriquecidos")

    bios = ingest_player_bios(only_missing=True)
    console.print(f"  {bios['actualizados']:,} biografías nuevas")

    compute_derived_columns()
    refresh_views()
    console.print("[green]Actualización diaria completada.[/green]")


if __name__ == "__main__":
    app()
