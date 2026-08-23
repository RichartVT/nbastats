"""Esquema de la base de datos (star schema).

Tres decisiones que condicionan todo lo demás:

1. `Game.game_id` es TEXTO, no entero. Los ids de la NBA vienen con ceros a la
   izquierda ("0022300001"); convertirlos a int los corrompe silenciosamente.

2. `Game.game_date_local` es la fecha en la zona del estadio, no en UTC. Un
   partido con salto inicial el viernes 22:30 ET en Los Ángeles es sábado en
   UTC — derivar el día de la semana desde UTC sesgaría sistemáticamente todos
   los splits por día, que es justo el análisis que nos interesa.

3. Los minutos se guardan como `seconds_played` (entero). La fuente los da como
   "34:12" y a veces como "34.000000:12"; todo el cálculo per-36 y per-100
   depende de haberlos normalizado una sola vez, en la ingesta.
"""

from __future__ import annotations

import datetime as dt
import enum
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SeasonType(enum.StrEnum):
    REGULAR = "regular"
    PLAYIN = "playin"
    PLAYOFFS = "playoffs"
    PRESEASON = "preseason"


# --- Tipos reutilizables -------------------------------------------------
# Conteos de un partido: nada supera los ~100, caben de sobra en SMALLINT.
Count = SmallInteger

# Porcentajes, SIEMPRE como fracción 0-1 (0.597, no 59.7). Se deja estrecho a
# propósito: fue este límite el que detectó que la API devuelve E_TOV_PCT en
# escala 0-100 mientras el resto viene en 0-1. Un tipo ancho lo habría tragado
# en silencio y el TOV% habría salido 100 veces mayor que el USG% en cada
# comparación. Margen por encima de 1 porque el TS% de un partido llega a 1.5.
Pct = Numeric(6, 4)

# Ratings, pace y posesiones. Ancho a propósito, al revés que Pct: el pace a
# nivel de JUGADOR es una extrapolación a 48 minutos y con estancias de segundos
# se dispara (se han observado 14.400 en un jugador con 0,5 min y 1 posesión).
# Es un valor real de la fuente, no un error de escala, así que se guarda tal
# cual y se avisa en CAPABILITIES.md de que no es interpretable con pocos
# minutos. Los ratings se mueven en ±300 y el pace de equipo en 85-115.
Rate = Numeric(9, 3)


# =========================================================================
# Dimensiones
# =========================================================================


class Team(Base):
    __tablename__ = "teams"

    team_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    abbreviation: Mapped[str] = mapped_column(String(5), index=True)
    full_name: Mapped[str] = mapped_column(String(80))
    city: Mapped[str | None] = mapped_column(String(60))
    nickname: Mapped[str | None] = mapped_column(String(60))
    conference: Mapped[str | None] = mapped_column(String(10))
    division: Mapped[str | None] = mapped_column(String(20))
    # Zona IANA del estadio ("America/Los_Angeles"). La usa la ingesta para
    # derivar game_date_local a partir del tipoff en UTC.
    arena_timezone: Mapped[str | None] = mapped_column(String(50))


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100), index=True)
    first_name: Mapped[str | None] = mapped_column(String(50))
    last_name: Mapped[str | None] = mapped_column(String(50))
    # Necesario para las curvas de edad: sin fecha de nacimiento no se puede
    # separar "declive normal por edad" de "declive anómalo".
    birthdate: Mapped[dt.date | None] = mapped_column(Date)
    height_cm: Mapped[int | None] = mapped_column(SmallInteger)
    weight_kg: Mapped[int | None] = mapped_column(SmallInteger)
    # La NBA no usa códigos cortos ("PG", "SF") sino palabras completas con
    # guion: "Center-Forward" son 14 caracteres. String(10) reventaba la carga.
    position: Mapped[str | None] = mapped_column(String(20))
    draft_year: Mapped[int | None] = mapped_column(SmallInteger)
    country: Mapped[str | None] = mapped_column(String(60))
    from_year: Mapped[int | None] = mapped_column(SmallInteger)
    to_year: Mapped[int | None] = mapped_column(SmallInteger)


class Season(Base):
    __tablename__ = "seasons"

    # Formato NBA: '2024-25'
    season_id: Mapped[str] = mapped_column(String(7), primary_key=True)
    year_start: Mapped[int] = mapped_column(SmallInteger)
    year_end: Mapped[int] = mapped_column(SmallInteger)
    regular_season_start: Mapped[dt.date | None] = mapped_column(Date)
    regular_season_end: Mapped[dt.date | None] = mapped_column(Date)


# =========================================================================
# Hechos
# =========================================================================


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        Index("ix_games_season_date", "season_id", "game_date_local"),
        Index("ix_games_date", "game_date_local"),
        Index("ix_games_home_team", "home_team_id", "game_date_local"),
        Index("ix_games_away_team", "away_team_id", "game_date_local"),
    )

    game_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    season_id: Mapped[str] = mapped_column(
        String(7), ForeignKey("seasons.season_id"), index=True
    )
    season_type: Mapped[SeasonType] = mapped_column(
        Enum(
            SeasonType,
            name="season_type",
            native_enum=True,
            # Sin esto SQLAlchemy guarda los NOMBRES de miembro ('REGULAR') en
            # vez de los valores ('regular'), y el SQL escrito a mano deja de
            # coincidir con lo que serializa la API.
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        index=True,
    )

    # Fecha en la zona del estadio. Fuente de verdad para el día de la semana.
    game_date_local: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # Instante exacto del salto inicial. Puede faltar en datos históricos;
    # game_date_local no.
    tipoff_utc: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    home_team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("teams.team_id"))
    away_team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("teams.team_id"))
    home_pts: Mapped[int | None] = mapped_column(Count)
    away_pts: Mapped[int | None] = mapped_column(Count)

    ot_periods: Mapped[int] = mapped_column(SmallInteger, default=0)
    attendance: Mapped[int | None] = mapped_column(Integer)
    arena_name: Mapped[str | None] = mapped_column(String(100))

    # Partido en sede neutral: París, Ciudad de México, Las Vegas (NBA Cup)...
    # La NBA designa un local nominal por contabilidad, pero NO hay ventaja de
    # campo: ni público propio, ni rutina, ni ausencia de viaje. Dejarlos
    # mezclados corrompería el split local/visitante, que es uno de los
    # análisis centrales del proyecto. En 2024-25 hubo 5 de 1.230.
    is_neutral_site: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])


class TeamGameStats(Base):
    """Box score de equipo. Una fila por equipo y partido (dos por partido)."""

    __tablename__ = "team_game_stats"
    __table_args__ = (
        Index("ix_tgs_team_game", "team_id", "game_id"),
        CheckConstraint("seconds_played >= 0", name="ck_tgs_seconds_nonneg"),
    )

    game_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("games.game_id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.team_id"), primary_key=True
    )

    # Desnormalizado a propósito: aparece en casi toda consulta de splits y
    # ahorra un join a games cada vez.
    opponent_team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("teams.team_id"))
    is_home: Mapped[bool] = mapped_column(Boolean)
    won: Mapped[bool | None] = mapped_column(Boolean)

    seconds_played: Mapped[int | None] = mapped_column(Integer)
    pts: Mapped[int | None] = mapped_column(Count)
    fgm: Mapped[int | None] = mapped_column(Count)
    fga: Mapped[int | None] = mapped_column(Count)
    fg3m: Mapped[int | None] = mapped_column(Count)
    fg3a: Mapped[int | None] = mapped_column(Count)
    ftm: Mapped[int | None] = mapped_column(Count)
    fta: Mapped[int | None] = mapped_column(Count)
    oreb: Mapped[int | None] = mapped_column(Count)
    dreb: Mapped[int | None] = mapped_column(Count)
    reb: Mapped[int | None] = mapped_column(Count)
    ast: Mapped[int | None] = mapped_column(Count)
    stl: Mapped[int | None] = mapped_column(Count)
    blk: Mapped[int | None] = mapped_column(Count)
    tov: Mapped[int | None] = mapped_column(Count)
    pf: Mapped[int | None] = mapped_column(Count)
    plus_minus: Mapped[int | None] = mapped_column(SmallInteger)

    # Avanzadas de equipo. `possessions` es el denominador de todo lo per-100.
    possessions: Mapped[Decimal | None] = mapped_column(Rate)
    pace: Mapped[Decimal | None] = mapped_column(Rate)
    off_rating: Mapped[Decimal | None] = mapped_column(Rate)
    def_rating: Mapped[Decimal | None] = mapped_column(Rate)
    net_rating: Mapped[Decimal | None] = mapped_column(Rate)
    efg_pct: Mapped[Decimal | None] = mapped_column(Pct)
    ts_pct: Mapped[Decimal | None] = mapped_column(Pct)

    # Derivadas post-carga con funciones de ventana sobre game_date_local.
    # NULL = todavía no calculadas (ver db/derive.py).
    rest_days: Mapped[int | None] = mapped_column(SmallInteger)
    is_back_to_back: Mapped[bool | None] = mapped_column(Boolean)


class PlayerGameStats(Base):
    """Box score tradicional de jugador. Una fila por jugador y partido.

    Se guardan también los DNP (`seconds_played = 0`, `dnp_reason` informado):
    distinguir "no jugó" de "no existe la fila" importa para contar partidos
    disponibles y para no inflar promedios.
    """

    __tablename__ = "player_game_stats"
    __table_args__ = (
        # El acceso dominante es por jugador ("dame su game log"), así que el
        # índice va encabezado por player_id aunque la PK sea (game, player).
        Index("ix_pgs_player_game", "player_id", "game_id"),
        Index("ix_pgs_team", "team_id"),
        CheckConstraint(
            "seconds_played >= 0 AND seconds_played <= 4800",
            name="ck_pgs_seconds_range",
        ),
    )

    game_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("games.game_id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.player_id"), primary_key=True
    )
    # Equipo del jugador EN ESE PARTIDO. Resuelve traspasos a mitad de
    # temporada sin ninguna lógica especial.
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("teams.team_id"))

    started: Mapped[bool | None] = mapped_column(Boolean)
    seconds_played: Mapped[int] = mapped_column(Integer, default=0)
    dnp_reason: Mapped[str | None] = mapped_column(Text)

    pts: Mapped[int | None] = mapped_column(Count)
    fgm: Mapped[int | None] = mapped_column(Count)
    fga: Mapped[int | None] = mapped_column(Count)
    fg3m: Mapped[int | None] = mapped_column(Count)
    fg3a: Mapped[int | None] = mapped_column(Count)
    ftm: Mapped[int | None] = mapped_column(Count)
    fta: Mapped[int | None] = mapped_column(Count)
    oreb: Mapped[int | None] = mapped_column(Count)
    dreb: Mapped[int | None] = mapped_column(Count)
    reb: Mapped[int | None] = mapped_column(Count)
    ast: Mapped[int | None] = mapped_column(Count)
    stl: Mapped[int | None] = mapped_column(Count)
    blk: Mapped[int | None] = mapped_column(Count)
    tov: Mapped[int | None] = mapped_column(Count)
    pf: Mapped[int | None] = mapped_column(Count)
    plus_minus: Mapped[int | None] = mapped_column(SmallInteger)


class PlayerGameAdvanced(Base):
    """Box score avanzado de jugador.

    Separado de la tabla tradicional porque tiene otra procedencia (otro
    endpoint / otra tabla del seed) y puede faltar para partidos antiguos sin
    que eso invalide la fila tradicional.
    """

    __tablename__ = "player_game_advanced"
    __table_args__ = (Index("ix_pga_player_game", "player_id", "game_id"),)

    game_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("games.game_id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.player_id"), primary_key=True
    )

    ts_pct: Mapped[Decimal | None] = mapped_column(Pct)
    efg_pct: Mapped[Decimal | None] = mapped_column(Pct)
    usg_pct: Mapped[Decimal | None] = mapped_column(Pct)
    ast_pct: Mapped[Decimal | None] = mapped_column(Pct)
    reb_pct: Mapped[Decimal | None] = mapped_column(Pct)
    oreb_pct: Mapped[Decimal | None] = mapped_column(Pct)
    dreb_pct: Mapped[Decimal | None] = mapped_column(Pct)
    tov_pct: Mapped[Decimal | None] = mapped_column(Pct)
    off_rating: Mapped[Decimal | None] = mapped_column(Rate)
    def_rating: Mapped[Decimal | None] = mapped_column(Rate)
    net_rating: Mapped[Decimal | None] = mapped_column(Rate)
    pace: Mapped[Decimal | None] = mapped_column(Rate)
    pie: Mapped[Decimal | None] = mapped_column(Pct)


class IngestLog(Base):
    """Auditoría de ingesta: permite reanudar, depurar y verificar idempotencia."""

    __tablename__ = "ingest_log"
    __table_args__ = (Index("ix_ingest_log_fetched", "fetched_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30))  # 'kaggle' | 'nba_api'
    endpoint: Mapped[str] = mapped_column(String(80))
    params: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))  # 'ok' | 'error' | 'empty'
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
