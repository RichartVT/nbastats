"""Interfaz de línea de comandos.

    uv run nbastats status                # qué hay cargado
    uv run nbastats setup                 # migraciones + vistas
    uv run nbastats ingest-seasons        # carga histórica completa
    uv run nbastats ingest-bios           # ficha de jugador (nacimiento, dorsal…)
    uv run nbastats ingest-teams          # fichas, plantillas y clasificación
    uv run nbastats enrich                # hora de inicio, sede y tipo de partido
    uv run nbastats ingest-periods        # box score por cuarto (masivo, ~5 min)
    uv run nbastats ingest-summaries      # resumen por partido (uno a uno, ~1,3 h)
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
                       m.PlayerGameStats, m.PlayerGameAdvanced,
                       m.PlayerPeriodStats, m.GamePeriodScore, m.GameOfficial,
                       m.PlayByPlay):
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

        con_dorsal = s.scalar(
            select(func.count()).select_from(m.Player).where(m.Player.jersey_number.isnot(None))
        )
        etiquetados = s.scalar(
            select(func.count()).select_from(m.Game).where(m.Game.game_label.isnot(None))
        )
        plantillas = s.scalar(select(func.count()).select_from(m.TeamSeasonRoster))
        clasif = s.scalar(select(func.count()).select_from(m.TeamStanding))
        con_estadio = s.scalar(
            select(func.count()).select_from(m.Team).where(m.Team.arena.isnot(None))
        )
        cob.add_row(
            "Dorsal y estatus", f"{con_dorsal:,}/{total_jug:,}" if total_jug else "—",
            "ficha de jugador",
        )
        cob.add_row("Etiqueta de partido", f"{etiquetados:,}", "NBA Cup, partidos internacionales")
        cob.add_row("Fichas de equipo", f"{con_estadio:,}/30", "estadio, entrenador, GM")
        cob.add_row("Plantillas", f"{plantillas:,}", "quién jugaba en cada equipo y año")
        cob.add_row("Clasificación", f"{clasif:,}", "posiciones y récords")

        con_cuartos = s.scalar(
            select(func.count(func.distinct(m.GamePeriodScore.game_id)))
        )
        jug_con_cuartos = s.scalar(
            select(func.count(func.distinct(m.PlayerPeriodStats.game_id)))
        )
        cob.add_row(
            "Marcador por cuarto", f"{con_cuartos:,}/{total_part:,}" if total_part else "—",
            "ficha de partido, remontadas",
        )
        cob.add_row(
            "Box por cuarto", f"{jug_con_cuartos:,}/{total_part:,}" if total_part else "—",
            "rendimiento por cuarto del jugador",
        )
        con_pbp = s.scalar(select(func.count(func.distinct(m.PlayByPlay.game_id))))
        con_puntos = s.scalar(
            select(func.count()).select_from(m.TeamGameStats)
            .where(m.TeamGameStats.pts_paint.isnot(None))
        )
        total_tgs = s.scalar(select(func.count()).select_from(m.TeamGameStats))
        cob.add_row(
            "Play-by-play", f"{con_pbp:,}/{total_part:,}" if total_part else "—",
            "clutch, rachas, zonas de tiro, quintetos",
        )
        cob.add_row(
            "Origen de los puntos", f"{con_puntos:,}/{total_tgs:,}" if total_tgs else "—",
            "pintura, contraataque, tras pérdida",
        )
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


@app.command("ingest-periods")
def ingest_periods_cmd(
    seasons: str = typer.Option("", help="Coma-separadas. Vacío = las del .env"),
    verbose: bool = False,
) -> None:
    """Box score de jugador por cuarto. ~75 peticiones, ~2 minutos.

    Es masivo, no por partido: `PlayerGameLogs` acepta `Period` y devuelve la
    temporada entera restringida a un cuarto en una sola llamada. Al terminar
    comprueba que la suma de los periodos reproduce el total del partido.
    """
    _configurar_logging(verbose)
    from nbastats.ingest.periods import ingest_periods, verificar_cuadre

    lista = [x.strip() for x in seasons.split(",") if x.strip()] or get_settings().season_list
    r = ingest_periods(lista)
    console.print(f"[green]{r['filas']:,} filas en {r['peticiones']} peticiones[/green]")

    v = verificar_cuadre(lista)
    malos = sum(v[k] for k in v if k != "comparados")
    color = "green" if malos == 0 else "red"
    console.print(
        f"[{color}]Cuadre: {v['comparados']:,} jugador-partido comparados, "
        f"{malos} descuadres[/{color}]"
    )
    if malos:
        console.print(f"[yellow]{ {k: v[k] for k in v if k != 'comparados' and v[k]} }[/yellow]")


@app.command("ingest-summaries")
def ingest_summaries_cmd(
    seasons: str = typer.Option("", help="Coma-separadas. Vacío = todas las cargadas"),
    all_games: bool = typer.Option(False, "--all", help="Reprocesar también los ya cargados"),
    limit: int = typer.Option(0, help="Solo los N primeros pendientes. Para probar"),
    verbose: bool = False,
) -> None:
    """Marcador por cuarto, pabellón, asistencia y árbitros.

    UNA PETICIÓN POR PARTIDO: ~6.600 peticiones y ~1,5 h para la carga completa.
    Es la primera ingesta del proyecto que no es masiva. Se puede interrumpir y
    relanzar: retoma por los partidos que falten.

    Pruébalo antes con `--limit 20`.
    """
    _configurar_logging(verbose)
    from nbastats.ingest.summaries import ingest_game_summaries

    lista = [x.strip() for x in seasons.split(",") if x.strip()] or None
    r = ingest_game_summaries(lista, only_missing=not all_games, limit=limit or None)
    console.print(
        f"[green]{r['pedidos'] - r['fallidos']:,} partidos · "
        f"{r['periodos']:,} filas de marcador por periodo[/green]"
    )
    if r["fallidos"]:
        console.print(
            f"[yellow]{r['fallidos']} fallidos: vuelve a lanzarlo para reintentar[/yellow]"
        )


@app.command("ingest-starters")
def ingest_starters_cmd(
    seasons: str = typer.Option("", help="Coma-separadas. Vacío = todas las cargadas"),
    all_games: bool = typer.Option(False, "--all", help="Reprocesar también los ya cargados"),
    limit: int = typer.Option(0, help="Solo los N primeros pendientes. Para probar"),
    verbose: bool = False,
) -> None:
    """Titularidad y motivo de DNP: quién salió de inicio y quién no jugó.

    UNA PETICIÓN POR PARTIDO: ~6.600 peticiones y algo más de una hora para la
    carga completa. `PlayerGameLogs` no distingue titular de suplente ni trae a
    los que no jugaron; `BoxScoreTraditionalV3` sí. Reanudable: retoma por los
    partidos en los que ninguna fila tiene `started` informado.

    TIENE QUE CORRER EN CADA PASADA DIARIA. `daily` recarga la temporada en
    curso entera, y los partidos recargados vuelven con `started` sin informar
    hasta que esto pasa por ellos.
    """
    _configurar_logging(verbose)
    from nbastats.ingest.starters import ingest_starters

    lista = [x.strip() for x in seasons.split(",") if x.strip()] or None
    r = ingest_starters(lista, only_missing=not all_games, limit=limit or None)
    console.print(
        f"[green]{r['pedidos']:,} partidos · {r['actualizadas']:,} filas con "
        f"titularidad · {r['nuevas']:,} filas de DNP nuevas[/green]"
    )
    if r["fallidos"]:
        console.print(
            f"[yellow]{r['fallidos']} sin box score: vuelve a lanzarlo para reintentar[/yellow]"
        )


@app.command("ingest-pbp")
def ingest_pbp_cmd(
    seasons: str = typer.Option("", help="Coma-separadas. Vacío = todas"),
    limit: int = typer.Option(0, help="Solo los N primeros pendientes. Para probar"),
    verbose: bool = False,
) -> None:
    """Play-by-play: cada evento de cada partido.

    UNA PETICIÓN POR PARTIDO: ~6.600 peticiones y ~3 h, ~3,5 M filas. Se puede
    interrumpir y relanzar; retoma por los partidos que falten, empezando por
    los más recientes.
    """
    _configurar_logging(verbose)
    from nbastats.ingest.playbyplay import ingest_play_by_play, verificar_marcador

    lista = [x.strip() for x in seasons.split(",") if x.strip()] or None
    r = ingest_play_by_play(lista, limit=limit or None)
    console.print(
        f"[green]{r['pedidos'] - r['fallidos']:,} partidos · {r['eventos']:,} eventos[/green]"
    )
    if r["fallidos"]:
        console.print(f"[yellow]{r['fallidos']} sin play-by-play en la fuente[/yellow]")

    v = verificar_marcador()
    malos = v["comprobados"] - v["cuadran"]
    color = "green" if malos == 0 else "red"
    console.print(
        f"[{color}]Marcador: {v['cuadran']:,}/{v['comprobados']:,} partidos "
        f"cuadran con el resultado final[/{color}]"
    )


@app.command("build-ratings")
def build_ratings_cmd(verbose: bool = False) -> None:
    """Calcula los ratings ajustados por rival y el backtest, y los guarda.

    No pide nada a la NBA: es todo cálculo sobre lo que ya está cargado. Tarda
    unos minutos porque reajusta la regresión una vez por jornada, que es lo
    que garantiza que ningún partido vea el futuro.
    """
    _configurar_logging(verbose)
    from nbastats.ratings_job import rebuild_ratings

    m = rebuild_ratings()
    if not m["partidos"]:
        console.print("[yellow]No hay partidos que ajustar.[/yellow]")
        return

    console.print(f"[bold]{m['partidos']:,} partidos.[/bold]")
    console.print(
        f"[green]{m['temporadas']} temporadas de ratings · {m['modelos']} modelos · "
        f"{m['predicciones']:,} predicciones guardadas[/green]"
    )
    console.print(
        f"  acierto {100*m['acierto']:.2f}%  ·  Brier {m['brier']:.4f}  ·  "
        f"log-loss {m['log_loss']:.4f}  ·  BSS {m['bss']:.4f}"
    )
    color = "green" if m["within_noise"] else "yellow"
    console.print(
        f"[{color}]  calibración: pendiente {m['slope']:.2f}, ECE {m['ece']:.4f} "
        f"(suelo {m['ece_floor']:.4f})[/{color}]"
    )


@app.command("ingest-teams")
def ingest_teams_cmd(
    seasons: str = typer.Option("", help="Coma-separadas. Vacío = las del .env"),
    verbose: bool = False,
) -> None:
    """Ficha de los equipos, plantillas por temporada y clasificación."""
    _configurar_logging(verbose)
    from nbastats.ingest.teams import ingest_all_team_data

    lista = [x.strip() for x in seasons.split(",") if x.strip()] or get_settings().season_list
    r = ingest_all_team_data(lista)
    console.print(
        f"[green]{r['equipos']} fichas · {r['plantillas']:,} fichas de plantilla · "
        f"{r['clasificacion']} filas de clasificación[/green]"
    )
    if r["plantillas_omitidas"]:
        console.print(
            f"[yellow]{r['plantillas_omitidas']} jugadores de plantilla omitidos "
            f"(nunca disputaron un partido)[/yellow]"
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
    en ~1 segundo, así que la parte masiva son ~25 peticiones: más simple que
    cualquier lógica incremental, y recoge gratis las correcciones oficiales de
    box scores que la NBA publica días después de cada partido.

    La parte por partido (los resúmenes) va aparte y **solo pide los que
    faltan**: unos 8-13 partidos en una noche de competición, no los 6.602. Es
    lo que mantiene el coste diario en minutos aunque la carga histórica llevara
    hora y media.
    """
    _configurar_logging(verbose)
    from nbastats.db.maintenance import compute_derived_columns, refresh_views
    from nbastats.ingest.bio import ingest_player_bios
    from nbastats.ingest.bulk import ingest_seasons
    from nbastats.ingest.enrich import enrich_games
    from nbastats.ingest.periods import ingest_periods, verificar_cuadre
    from nbastats.ingest.playbyplay import ingest_play_by_play
    from nbastats.ingest.starters import ingest_starters
    from nbastats.ingest.summaries import ingest_game_summaries
    from nbastats.ingest.teams import ingest_all_team_data
    from nbastats.ratings_job import rebuild_ratings

    season = temporada_actual()
    console.print(f"[bold]Temporada actual: {season}[/bold]")

    res = ingest_seasons([season])
    console.print(f"  {sum(r.games for r in res):,} partidos")

    enriquecido = enrich_games(only_missing=True)
    console.print(f"  {enriquecido['partidos']:,} partidos enriquecidos")

    bios = ingest_player_bios(only_missing=True)
    console.print(f"  {bios['actualizados']:,} biografías nuevas")

    equipos = ingest_all_team_data([season])
    console.print(
        f"  {equipos['equipos']} fichas de equipo, {equipos['plantillas']} de plantilla"
    )

    periodos = ingest_periods([season])
    console.print(f"  {periodos['filas']:,} filas por cuarto")

    # Solo los partidos sin resumen: los de anoche, no los 6.602.
    resumenes = ingest_game_summaries([season], only_missing=True)
    console.print(f"  {resumenes['pedidos'] - resumenes['fallidos']:,} resúmenes de partido")

    # NO ES OPCIONAL, por el mismo motivo que los ratings. `ingest_seasons`
    # inserta a los que jugaron sin `started`, así que sin esta línea la
    # titularidad de la temporada en curso se queda sin informar: los splits
    # titular/suplente meterían a los cinco titulares en 'suplente', porque
    # `CASE WHEN NULL` cae al ELSE, y `games_started` daría 0 en toda la
    # temporada. Solo los partidos que falten: los de anoche, no los 6.602.
    titulares = ingest_starters([season], only_missing=True)
    console.print(
        f"  {titulares['actualizadas']:,} filas con titularidad, "
        f"{titulares['nuevas']:,} DNP"
    )

    # Solo los partidos sin play-by-play: ~10 en una noche, no los 6.602.
    pbp = ingest_play_by_play([season], only_missing=True)
    console.print(f"  {pbp['eventos']:,} eventos de play-by-play")

    compute_derived_columns()
    refresh_views()

    # LOS RATINGS SE REAJUSTAN AQUÍ, Y NO ES OPCIONAL. Las consultas resuelven
    # la temporada con `COALESCE(:season, MAX(...))` y no hay marca de
    # obsolescencia: si esto no corre, el primer día de una temporada nueva
    # `/ratings` y `/predict` servirán la anterior como si fuera la actual, sin
    # error y sin aviso. No cuesta ninguna petición, solo cálculo.
    m = rebuild_ratings()
    if m["partidos"]:
        console.print(
            f"  ratings de {m['temporadas']} temporadas · "
            f"{m['predicciones']:,} predicciones · acierto {100*m['acierto']:.2f}%"
        )

    # El cuadre de los cuartos se comprueba en cada actualización, no solo en la
    # carga inicial: si un día la API deja de aceptar `Period`, devolvería el
    # total del partido en los cuatro cuartos y nadie se enteraría.
    v = verificar_cuadre([season])
    malos = sum(v[k] for k in v if k != "comparados")
    if malos:
        console.print(
            f"[red]AVISO: {malos} descuadres entre los cuartos y el total "
            f"del partido en {season}[/red]"
        )

    console.print("[green]Actualización diaria completada.[/green]")


if __name__ == "__main__":
    app()
