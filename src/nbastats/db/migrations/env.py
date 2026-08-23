"""Entorno de Alembic.

La URL de conexión sale de nbastats.config (.env), no de alembic.ini, para que
haya una sola fuente de verdad.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from nbastats.config import get_settings
from nbastats.db.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Objetos que existen en la base pero NO en los modelos, porque los crea SQL
# crudo dentro de una migración. Sin este filtro, `alembic revision
# --autogenerate` los ve como sobrantes y genera un DROP silencioso: ya pasó
# una vez con el índice de búsqueda sin acentos, que desapareció al migrar una
# columna que no tenía nada que ver.
OBJETOS_NO_GESTIONADOS = {
    "ix_players_name_unaccent",  # índice funcional sobre immutable_unaccent()
}


def include_object(object_, name, type_, reflected, compare_to):  # noqa: ANN001
    return not (type_ == "index" and name in OBJETOS_NO_GESTIONADOS)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detecta cambios de tipo además de columnas añadidas/quitadas.
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
