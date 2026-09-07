# nbastats

Plataforma de estadísticas NBA orientada a **detectar patrones**: jugadores en
declive, jugadores al alza y rendimiento condicionado (día, descanso, rival,
localía) sobre cinco temporadas.

El objetivo no es guardar números, sino producir conclusiones que aguanten.

## La documentación, y para qué sirve cada pieza

| Documento | Para qué |
|---|---|
| [`COMO_FUNCIONA.md`](COMO_FUNCIONA.md) | **Empieza aquí.** El recorrido de un dato de la NBA a la pantalla, y cómo se calcula un pronóstico paso a paso |
| [`CONCLUSIONES.md`](CONCLUSIONES.md) | Qué sabe hacer el sistema **con el número al lado**, qué está en su techo y qué haría falta para mejorarlo |
| [`CAPABILITIES.md`](CAPABILITIES.md) | El contrato: qué preguntas se pueden contestar y cuáles devuelven un número que no significa nada |
| [`BITACORA.md`](BITACORA.md) | El registro cronológico de las 24 fases, con los resultados negativos incluidos |

Las dos primeras son las que explican el sistema; las dos últimas son las que
impiden usarlo mal.

## Requisitos

- Docker (para Postgres 17)
- [`uv`](https://docs.astral.sh/uv/) (gestiona Python 3.12 y las dependencias)

## Puesta en marcha

```bash
cp .env.example .env       # valores por defecto ya sirven
docker compose up -d       # Postgres en localhost:5433
uv sync                    # Python 3.12 + dependencias
uv run alembic upgrade head
uv run pytest
```

El puerto es el **5433**, no el 5432, para no chocar con el `postgresql@14` de
Homebrew.

Para entrar a la base:

```bash
docker exec -it nbastats-db psql -U nbastats -d nbastats
```

## Cargar los datos

```bash
uv run nbastats ingest-seasons   # box scores, 5 temporadas (~3 min)
uv run nbastats enrich           # hora de inicio y sedes neutrales (~10 min)
uv run nbastats ingest-bios      # ficha de jugador: nacimiento, dorsal… (~12 min)
uv run nbastats ingest-teams     # fichas, plantillas y clasificación (~3 min)
uv run nbastats refresh          # columnas derivadas y vistas
uv run nbastats status           # ver qué hay cargado
```

Después, `uv run nbastats daily` mantiene todo al día en un solo comando.

## Levantar la aplicación

Dos procesos, en dos terminales:

```bash
uv run uvicorn nbastats.api.main:app --reload    # API en :8000, /docs incluido
cd web && npm install && npm run dev             # interfaz en :5173
```

El frontend habla con la API por un proxy de Vite, así que usa rutas relativas
y no hay que configurar CORS en desarrollo.

## Estructura

```
src/nbastats/
├── config.py           Configuración desde .env
├── cli.py              Comandos
├── db/
│   ├── models.py       Esquema (star schema)
│   ├── maintenance.py  Columnas derivadas y vistas materializadas
│   ├── sql/            derive.sql, views.sql
│   └── migrations/     Alembic
├── ingest/
│   ├── nba_client.py   Cliente con control de ritmo y reintentos
│   ├── teams.py        Fichas de equipo, plantillas y clasificación
│   ├── bulk.py         Carga de temporadas completas
│   ├── enrich.py       Hora de inicio y sedes neutrales
│   ├── bio.py          Biografías de jugadores
│   └── transforms.py   Normalizaciones de la fuente
├── analysis/
│   ├── rates.py        per-36, per-100, TS%, eFG%, USG%, Game Score
│   ├── trends.py       Declive/alza: Mann-Kendall, puntos de cambio, edad
│   ├── game_types.py   Tipo de partido: NBA Cup, playoffs, internacionales
│   └── reliability.py  Splits con intervalo, encogimiento y control de FDR
└── api/
    ├── catalog.py      Estadísticas y dimensiones consultables
    ├── queries.py      Consultas sobre las vistas materializadas
    ├── schemas.py      Contrato de la API (y origen de los tipos TS)
    └── main.py         Endpoints

web/                    React + Vite + TypeScript + Recharts
├── src/api/            Cliente y tipos espejo de los esquemas Pydantic
├── src/components/     Gráficos e insignias de confiabilidad
└── src/pages/          Jugadores, equipos, clasificación, rankings
```

## Datos

Fuente única: **`nba_api`** (stats.nba.com). Las 5 temporadas completas son
~6.600 partidos y ~141.000 filas jugador-partido.

El plan original usaba el dataset de Kaggle `wyattowalsh/basketball` como
semilla. Se descartó al comprobarlo: **no contiene box scores de jugador** (solo
datos a nivel de equipo y play-by-play), y su `common_player_info.csv` cubría
apenas 628 de nuestros 1.030 jugadores. Como `nba_api` devuelve una temporada
entera de box scores en ~1 segundo, la fuente única sale más rápida y más
simple.

> La ingesta debe correr **desde una máquina doméstica**. `stats.nba.com` está
> detrás de protección Akamai y descarta conexiones desde IPs de datacenter
> (AWS, GCP, Azure) sin devolver error: la petición se queda colgada hasta el
> timeout. El backend sí se puede desplegar a la nube; la ingesta no.

Uso personal y educativo. No redistribuir los datos crudos.

## Tres detalles del esquema que no son arbitrarios

1. **`game_id` es texto.** Los ids de la NBA llevan ceros a la izquierda
   (`"0022300001"`). Pasarlos por `int` desplaza el código y un partido de
   temporada regular pasa a leerse como All-Star. Hay un test que lo comprueba.

2. **`game_date_local`, no UTC.** Un partido que empieza el viernes a las 22:30
   en Nueva York son las 03:30 del sábado en UTC. Derivar el día de la semana
   desde UTC movería de día justo los partidos nocturnos y sesgaría todos los
   splits por día.

3. **Los minutos se guardan en segundos.** La fuente los da como `"34:12"` y a
   veces como `"34.000000:12"`. Se normalizan una sola vez, en la ingesta.

## Licencia

El **código** está bajo licencia [MIT](LICENSE).

Los **datos** no. Provienen de `stats.nba.com`, no están cubiertos por la
licencia MIT y este repositorio no los redistribuye: no hay ni un box score
versionado aquí. Para tener datos hay que descargarlos con los comandos de
ingesta, y ese uso es personal y educativo.
