# Bitácora de desarrollo

Registro del proceso: en qué fase vamos, qué paso viene ahora y por qué.

**Cómo se escribe:** cada paso se anota *antes* de ejecutarlo (objetivo y qué se
va a hacer) y se completa al terminar (resultado real y decisiones tomadas).
Cuando la realidad contradice al plan, se anota la contradicción en vez de
reescribir la historia — saber qué supuesto falló vale más que un plan que
parezca haber acertado siempre.

Documentos hermanos:
- [`README.md`](README.md) — cómo levantar y usar el proyecto
- [`CAPABILITIES.md`](CAPABILITIES.md) — qué preguntas se pueden contestar
- Plan original: `~/.claude/plans/hola-te-cuento-quiero-glittery-starfish.md`

---

## Estado por fases

| # | Entregable | Estado |
|---|---|---|
| 0 | Entorno: `uv` + Python 3.12, Postgres 17, esqueleto de repo | ✅ Completa |
| 1 | Esquema + migraciones Alembic + `CAPABILITIES.md` | ✅ Completa |
| 2 | Carga histórica de 5 temporadas | ✅ Completa — 6.602 partidos, 140.932 filas |
| 3 | Ingesta incremental + columnas derivadas | ✅ Completa — `nbastats daily` |
| 4 | Vistas materializadas + capa de análisis | ✅ Completa — validada contra la NBA |
| 5 | API FastAPI | ✅ Completa — 9 endpoints |
| 6 | Frontend React | ✅ Completa — 3 vistas, 2 gráficos, modo claro y oscuro |

**Números:** 6.602 partidos · 140.932 filas jugador-partido · 1.030 jugadores
con biografía completa · 5 temporadas (2021-22 → 2025-26) · 145 tests ·
7 migraciones · 9 endpoints.

---

## Registro cronológico

### 2026-08-22 · Fase 0 — Entorno

**Objetivo:** dejar el proyecto ejecutable antes de escribir lógica.

**Ejecutado:** `brew install uv`; `git init`; esqueleto `src/nbastats/`;
`docker compose up -d` con Postgres 17; `uv sync` con Python 3.12.

**Resultado:** Python 3.12.14, PostgreSQL 17.11 *healthy* en `localhost:5433`,
40 dependencias instaladas.

**Decisiones:**
- **Puerto 5433, no 5432.** La máquina ya tiene `postgresql@14` de Homebrew;
  usar el puerto por defecto habría provocado un choque silencioso difícil de
  diagnosticar.
- **Python 3.12 vía `uv`.** El sistema trae 3.9.6 y `nba_api` exige 3.10+.

---

### 2026-08-22 · Fase 1 — Esquema

**Objetivo:** modelar el dominio de forma que los análisis posteriores sean
posibles y correctos.

**Ejecutado:** `db/models.py` (9 tablas), migración inicial de Alembic,
`ingest/transforms.py`, `analysis/reliability.py`, `CAPABILITIES.md`, y 63 tests.

**Resultado:** esquema aplicado, tests en verde, `ruff` limpio.

**Decisiones y hallazgos:**

- **`game_id` es TEXTO.** Lo escribí en el plan por los ceros a la izquierda,
  pero al escribir el test descubrí que el daño real es peor: el id `0022300001`
  codifica el tipo de partido en la posición 3. Al pasar por `int` queda
  `22300001`, el código se desplaza y el dígito de tipo pasa de `2` (temporada
  regular) a `3` (**All-Star**). No se pierde un cero: el partido cambia de
  identidad sin avisar. → `tests/test_transforms.py::test_conserva_ceros_a_la_izquierda`

- **`game_date_local` en zona del estadio.** Un partido de viernes 22:30 en
  Nueva York es sábado 03:30 en UTC. Derivar el día desde UTC movería de día
  justo los partidos nocturnos.

- **Enum en minúsculas.** SQLAlchemy guarda por defecto los *nombres* de los
  miembros (`REGULAR`), no sus valores (`regular`). Lo detecté cuando el SQL
  escrito a mano falló contra la base. Corregido con `values_callable` y la
  migración `e42c161a7edf`, que renombra las etiquetas conservando los datos.

- **Umbrales de confiabilidad calculados, no supuestos.** Al calcular los `n`
  reales por tipo de split apareció un matiz importante sobre el ejemplo de los
  sábados: con **una** temporada no vale (n≈12), con **cinco** sí (n≈60) — pero
  entonces mezclas al jugador de 25 años con el de 30, que es justo lo que borra
  el análisis de declive. No se pueden tener las dos cosas del mismo número.
  Documentado en `CAPABILITIES.md` §3.

---

### 2026-08-22/23 · Fases 3 y 4 (adelantadas) — SQL derivado y análisis

**Objetivo:** avanzar en lo que no dependía de tener datos cargados, mientras la
Fase 2 esperaba credenciales.

**Ejecutado:** `db/sql/derive.sql`, `db/sql/views.sql`, `db/maintenance.py`,
`analysis/rates.py`, `analysis/trends.py` y sus tests (105 en total).

**Resultado:** el SQL ejecuta sin errores contra la base real (vacía). Las 3
vistas materializadas existen.

**Decisiones:**

- **Desviación del plan: no hay `mv_player_rolling`.** El plan preveía
  materializar medias móviles de 5/10/25 partidos. En su lugar se creó
  `mv_player_game_rates` (una fila por jugador-partido con las tasas ya
  normalizadas) y las ventanas se calculan al vuelo. Motivo: materializar 3
  ventanas × ~15 estadísticas añade ~45 columnas por fila que casi nunca se
  leen y obliga a refrescar todo en cada ingesta, mientras que calcular la media
  móvil de los ~350 partidos de un jugador en Python es instantáneo.

- **La regresión corre sobre valores crudos, nunca sobre la media móvil.**
  Suavizar y luego regresar autocorrelaciona los puntos y hunde el p-valor
  artificialmente. Hay un test que lo cuantifica: con ruido puro, la vía
  suavizada declara "tendencia" más de 3 veces más a menudo que la correcta.
  → `tests/test_trends.py::TestAutocorrelacion`

- **Se exigen dos tests de acuerdo** (Mann-Kendall + IC de la pendiente que
  excluya el cero) antes de declarar tendencia.

- **Las tasas agregadas se calculan sobre totales, no promediando tasas.**
  Promediar el TS% de cada partido pondera igual uno de 40 minutos y otro de 5.

---

### 2026-08-23 · Fase 2 — Bloqueo, desbloqueo y cambio de estrategia

**Objetivo:** cargar el histórico de 5 temporadas.

**Lo que decía el plan:** descargar el dataset `wyattowalsh/basketball` de Kaggle
(4,66 GB), que "incluye box scores tradicionales y avanzadas", y usar `nba_api`
solo para lo incremental.

**Lo que pasó al comprobarlo:** el token de Kaggle funciona, pero al listar los
20 ficheros reales del dataset aparecieron dos errores del plan:

1. **La licencia es CC BY-SA 4.0, no MIT.** Confundí la licencia del repo de
   código (MIT) con la del dataset publicado.

2. **El dataset NO tiene box scores de jugador.** Tiene `game.csv` (nivel
   *equipo*), `player.csv`, `team.csv`, `play_by_play.csv` y poco más. No hay
   ninguna tabla jugador-por-partido, que es exactamente lo que necesita este
   proyecto. El README de GitHub que consulté describe la versión nueva del
   warehouse (`nbadb.w4w.dev`); el dataset de Kaggle sigue con el esquema
   antiguo. Tampoco tiene shot charts.

**El hallazgo que lo resuelve:** probando alternativas, `nba_api` tiene el
endpoint `PlayerGameLogs`, que devuelve **una temporada entera de box scores de
jugador en una sola llamada de ~1 segundo**:

```
2021-22 regular   26,039 filas   1,230 partidos
2022-23 regular   25,894 filas   1,230 partidos
2023-24 regular   26,401 filas   1,230 partidos
2024-25 regular   26,306 filas   1,230 partidos
2025-26 regular   26,651 filas   1,230 partidos
```

Acepta `measure_type="Advanced"`, que devuelve TS%, eFG%, USG%, AST%, REB%,
ratings, PACE, POSS y PIE — justo las columnas de `player_game_advanced`. Y da
minutos exactos (`"48:24"`), no redondeados.

**Cambio de estrategia (invierte el plan):**

| | Plan original | Ahora |
|---|---|---|
| Box scores | Kaggle (4,66 GB) | `nba_api` en bloque, ~40 llamadas, ~2 min |
| Papel de `nba_api` | Solo incremental | Fuente principal |
| Papel de Kaggle | Fuente principal | Solo `common_player_info.csv` (~1 MB) para fechas de nacimiento |
| Tiempo estimado | 20-40 h | ~5 min |

Kaggle sigue haciendo falta porque `nba_api` solo da fechas de nacimiento con
una llamada por jugador (~600 llamadas), y sin ellas no hay curvas de edad.

**Verificado antes de decidir:** `stats.nba.com` responde desde esta Mac en
0,4 s; los 5 años dan 1.230 partidos regulares exactos cada uno; playoffs y
play-in también funcionan; `TeamGameLogs` da las 2.460 filas de equipo.

---

#### Paso 1 ✅ — `ingest/nba_client.py`

Envoltorio de `nba_api` con control de ritmo global al proceso (cerrojo
compartido: stats.nba.com limita por IP, así que varios clientes no irían más
rápido, solo conseguirían que nos bloqueen), reintentos con backoff exponencial
y el mapa de zonas horarias de los 30 estadios.

El mapa va por equipo y no por estado por tres excepciones que rompen cualquier
agrupación geográfica: **Phoenix no aplica horario de verano**
(`America/Phoenix`), Indiana tiene zona propia, y Toronto es Canadá.

**Hallazgo que simplifica el diseño:** comprobé si el `GAME_DATE` que devuelve
la API coincide con la fecha local del estadio, comparándolo contra
`gameTimeUTC` convertido a la zona de cada estadio. Probé 45 partidos en 6
fechas, incluidas las dos de cambio de horario de verano (3-nov-2024 y
9-mar-2025):

```
45 partidos revisados en 6 fechas
discrepancias entre GAME_DATE oficial y fecha local del estadio: 0
```

`GAME_DATE` **ya es** la fecha local. Eso ahorra ~1.000 llamadas de scoreboard
que el plan daba por necesarias. El mapa de zonas se queda igualmente: hace de
red de seguridad y hará falta si algún día guardamos `tipoff_utc`.

---

#### Pasos 2-4 ✅ — Carga en bloque, biografías y CLI

**Resultado: 6.602 partidos y 140.932 filas jugador-partido en 156 segundos, 0
descartados.** El plan estimaba 20-40 horas.

Tres bugs encontrados al cargar de verdad, los tres con la misma moraleja —
*el esquema estrecho hace de test*:

1. **`E_TOV_PCT` viene en escala 0-100** mientras que TS%, USG%, AST% y el resto
   vienen en 0-1, en la misma respuesta. Lo cazó el `Numeric(6,4)` de la
   columna. Con un tipo ancho habría entrado en silencio y el TOV% habría salido
   100 veces mayor que el USG% en cualquier gráfico o comparación. Se normaliza
   en `bulk._fraction()`.

2. **El `pace` de jugador llega a 14.400.** Es una extrapolación a 48 minutos:
   con 0,5 minutos jugados y 1 posesión, el número se dispara. Aquí sí es un
   valor real de la fuente, así que se ensanchó la columna a `Numeric(9,3)` en
   vez de alterarlo, y se documentó como no interpretable con pocos minutos.
   Decisión asimétrica deliberada: `Pct` sigue estrecho (detecta errores de
   escala), `Rate` va ancho (admite extrapolaciones legítimas).

3. **Partidos en sede neutral.** La primera carga daba 1.225 partidos en vez de
   1.230. Los 5 que faltaban tenían a los DOS equipos marcados con `@` en
   `MATCHUP`: eran París (×2), Ciudad de México y las semifinales de la NBA Cup
   en Las Vegas. Esto no era solo un fallo de parseo — **un partido "en casa"
   jugado en París no es un partido en casa**, y contarlo como tal contamina el
   split local/visitante, que es uno de los análisis centrales. Se añadió
   `games.is_neutral_site` y se resuelve el local nominal vía `ScoreboardV3`.

**Patrón nuevo para migraciones:** Postgres rechaza `ALTER COLUMN TYPE` si una
vista materializada depende de la columna. Como las vistas son artefactos
derivados, las migraciones las sueltan y `rebuild_views()` las recrea desde
`db/sql/views.sql`. Embeber una copia del SQL en la migración crearía una
segunda fuente de verdad.

**Kaggle eliminado del proyecto.** El plan usaba `common_player_info.csv` para
las fechas de nacimiento (1 MB, una descarga, en vez de ~1.000 peticiones). Al
comprobarlo, ese CSV solo cubría **628 de nuestros 1.030 jugadores** — le
faltaba el 39%, sobre todo novatos recientes. Como hacía falta `nba_api` para
el resto igualmente, se usa una sola fuente (`CommonPlayerInfo`, 0,28 s por
jugador). Eso quita del proyecto la credencial de Kaggle, la dependencia
`kagglehub` y la obligación de atribución CC BY-SA.

**Consecuencia útil para la Fase 3:** como `PlayerGameLogs` devuelve una
temporada entera en ~1 s, la "ingesta incremental" es simplemente **recargar la
temporada actual completa** — 4 peticiones. Más simple que cualquier lógica de
rangos de fechas, y recoge gratis las correcciones oficiales de box scores que
la NBA publica días después. Implementado en `nbastats daily`.

**Verificación (criterios del plan §12), toda en verde:**

```
1.230 partidos regulares en cada una de las 5 temporadas    ✅
13.204/13.204 team-partido donde la suma de puntos de los
  jugadores cuadra EXACTO con los del equipo                ✅
0 fechas nulas · 0 minutos absurdos · 0 avanzados huérfanos ✅
150 rest_days nulos = 30 equipos × 5 temporadas (correcto)  ✅
```

---

### Límites conocidos y aceptados

Cosas que la fuente no da y que conviene tener escritas en vez de descubrirlas
más tarde interpretando un número raro:

| Límite | Impacto | Coste de arreglarlo |
|---|---|---|
| `started` (titular/suplente) sin dato | No hay split titular vs. banquillo | 1 petición por partido (~6.600) |
| `dnp_reason` sin dato — solo aparecen los que jugaron | No se distingue "lesionado" de "no convocado" | Igual que el anterior |
| Sedes neutrales de **2022-23** no detectables | 2 partidos de 6.150 (0,03%) mal clasificados como local | Requiere una fuente externa |
| `pace` de jugador no interpretable con pocos minutos | Ninguno mientras no se promedie | No arreglable: es la métrica |

Sobre el tercero: la API expone `isNeutral` y `gameLabel` a partir de 2023-24,
pero **no los retropobló para 2022-23**. Se comprobaron `MATCHUP`, `isNeutral`,
`gameLabel`, `gameSubtype` y `BoxScoreSummaryV2` (que ni siquiera devuelve el
estadio) sin encontrar señal. Se deja el hueco documentado en vez de codificar
a mano dos `game_id` de memoria: un hueco conocido es mejor que un dato que
parece verificado y no lo está.

---

### 2026-08-23 · Fase 3 — Enriquecido y validación externa

**Enriquecido completado:** 1.056 fechas, **6.602/6.602 partidos con
`tipoff_utc`**, 0 sin encontrar. Eso habilita una dimensión de análisis nueva
(rendimiento según hora de inicio) que antes no existía.

#### Validación externa: contra la NBA, no contra mi memoria

El plan pedía validar a mano contra Basketball-Reference. Se hizo mejor:
contrastar nuestros agregados contra **`LeagueDashPlayerStats`**, el cálculo
oficial que la propia NBA publica. Es una agregación independiente de la misma
materia prima, así que comprueba todo el camino (ingesta → vista → agregado)
sin depender de que yo recuerde bien un promedio.

```
Referencia oficial NBA: 569 jugadores
Nuestros datos:         569 jugadores      ← coincide exacto

Shai Gilgeous-Alexander   32.7 / 32.7      5.0 / 5.0
Giannis Antetokounmpo     30.4 / 30.4     11.9 / 11.9
LeBron James              24.4 / 24.4      7.8 / 7.8
Stephen Curry             24.5 / 24.5      4.4 / 4.4
```

**Pero aparecieron discrepancias pequeñas en jugadores de rotación corta**, y
la pista fue que Luka Garza difería en exactamente 1 partido jugado. Causa: hay
**22 filas en toda la base donde un jugador aparece con 0 segundos** — entró a
pista con el crono a cero. La NBA los cuenta como partido jugado; mi vista los
filtraba con `seconds_played > 0`, lo que desviaba los promedios hasta 0,3
puntos.

Se adoptó la definición oficial. El criterio: si alguien mira NBA.com y ve 24,4
mientras nuestra app dice 24,5, eso es un error nuestro aunque la lógica interna
sea coherente. `mv_player_season` ahora expone dos columnas distintas:
`games_played` (toda aparición, para promedios por partido) y
`games_with_minutes` (denominador correcto para tasas, donde un partido de 0
minutos no puede aportar nada).

#### Un bug mío que empeoraba el dato de la fuente

Tras el enriquecido, 2024-25 pasó de 5 sedes neutrales a 9. Los 4 nuevos eran
los **cuartos de final de la NBA Cup**, que se juegan en la pista del mejor
clasificado y para los que la API devuelve explícitamente `isNeutral=False`.

El culpable era mi propio patrón: `semifinal|championship|final` casa con
`"final"` **dentro de `"Quarterfinal"`**. Corregido a
`\b(semifinal|championship)\b`, con tests que fijan el caso
(`tests/test_enrich.py`).

La lección va más allá del regex: **una heurística que pisa un dato directo de
la fuente es peor que no tener heurística.** El orden correcto es señal directa
primero, heurística solo donde no la hay.

---

### 2026-08-23 · Fase 5 — API

**9 endpoints funcionando.** `catalog.py` es la pieza que sostiene el resto: un
enum de estadísticas y dimensiones que hace tres cosas a la vez — impide la
inyección SQL (los nombres de columna nunca vienen del cliente, se resuelven
contra el catálogo), documenta la API sola en `/docs`, y declara qué métricas
son TASAS, que es lo que decide qué filas entran en cada análisis.

#### Un problema de usabilidad que solo aparece con datos reales

Buscar `Jokic` no encontraba a **Nikola Jokić**. Ni `Doncic` a **Dončić**, ni
`Vucevic` a **Vučević**. La NBA está llena de diacríticos y nadie los teclea.
Resuelto con la extensión `unaccent` de Postgres y un índice funcional sobre
`lower(immutable_unaccent(full_name))`. Hizo falta envolver `unaccent()` en una
función propia declarada IMMUTABLE: la original es STABLE (depende del
diccionario cargado) y Postgres no admite funciones no inmutables en un índice.

#### Resultados reales

Tendencias, y son correctas en términos de baloncesto:

```
LeBron James, puntos per-36:  DECLIVE
  n=312, -1.95 por temporada, IC95 [-2.69, -1.21], los dos tests coinciden
  + escalón detectado en el partido 100 -> "una sola recta describe mal
    esta trayectoria"

Nikola Jokić, TS%:            ESTABLE
  n=357, el cambio por temporada cabe en ±0.01, que incluye el cero
```

**Y el caso que originó todo el diseño**, los rebotes de Jokić por día de la
semana:

```
día          n   media cruda   a mostrar          IC95
lunes       54      13.24        13.26      [12.16, 14.32]
viernes     65      12.56        13.19      [11.61, 13.52]
sábado      49      12.72        13.21      [11.58, 13.86]
domingo     50      14.24        13.35      [13.08, 15.41]

any_distinguishable: False
```

Las medias crudas van de 12,56 a 14,24 — 1,7 rebotes de diferencia. Un
dashboard ingenuo titularía *"coge 14,2 rebotes los domingos y 12,6 los
viernes"*. El encogimiento las colapsa todas a ~13,2-13,3 y el sistema responde
literalmente: **"aquí no hay patrón, solo variación normal"**. Esto es el
requisito del proyecto funcionando de punta a punta.

El ranking de declive analiza 378 jugadores en ~1 segundo y devuelve 74
significativos tras corregir por FDR. Los primeros son Kyle Lowry, P.J. Tucker,
Gordon Hayward, Marcus Morris — veteranos de 35-41 años en el periodo. Plausible.

---

### 2026-08-23 · Fase 6 — Frontend

React 19 + Vite + TypeScript + Recharts + Tailwind 4. Tres vistas: buscador,
ficha de jugador (trayectoria + splits + temporadas) y rankings.

#### La decisión de diseño que más importa: la forma del gráfico de splits

Se descartaron las barras a favor de un **gráfico de puntos con bigotes de
intervalo de confianza**, y no es cosmética:

- Una barra afirma que el trayecto desde cero significa algo. En un promedio de
  rebotes no significa nada — nadie parte de cero.
- Peor: una barra alta se lee como "mucho" aunque su intervalo sea enorme.
- El punto con bigotes hace **visualmente obvio** lo único que importa aquí: si
  el intervalo cruza la línea del promedio del jugador, no hay nada que contar.

El color tampoco es categórico. Los 7 días no son entidades que haya que
distinguir entre sí, son el mismo jugador en circunstancias distintas: pintarlos
de 7 colores gastaría el canal en información que el eje ya da y haría que los 7
parecieran igual de reales. Aquí el color codifica otra cosa — **azul = se
distingue del azar, gris = no**. En la ficha de Jokić los 7 puntos salen grises.

La paleta se validó con el verificador de accesibilidad antes de usarla (banda
de luminosidad, suelo de croma, separación para daltonismo, contraste), en los
dos modos. Peor par adyacente: ΔE 9,1 en claro y 8,4 en oscuro.

#### Tres defectos que solo se vieron al renderizar

Compilar sin errores no dice nada sobre si un gráfico se lee. Al capturar la
página aparecieron:

1. **Los días salían de domingo a lunes.** Recharts coloca la primera categoría
   abajo. Un eje en orden antinatural hace que el ojo busque patrones donde no
   los hay — lo contrario del objetivo de la vista.
2. **Marcas de eje como `32.663399999999996`.** El dominio se derivaba de los
   valores con `dataMin - 1.5`.
3. **La etiqueta "su promedio" recortada** por el borde superior.

Los tres corregidos: dominio calculado sobre los extremos de los bigotes (no
sobre los puntos, que dejaba los intervalos fuera del eje) y redondeado a
enteros, eje invertido, margen superior ampliado.

#### Un hallazgo estadístico al validar las curvas de edad

Con las 1.030 biografías cargadas se pudo ajustar por fin la curva de edad de la
liga sobre datos reales. El resultado:

```
1.561 temporadas · pico ajustado: 29,0 años
  21 años -> 94,4% del pico       33 años -> 98,6%
  27 años -> 99,7%                39 años -> 91,2%
```

**Ese resultado no es creíble.** Un jugador de 39 años al 91% de su pico no
describe a ningún deportista real. Es **sesgo de supervivencia**: en la muestra
solo entran jugadores lo bastante buenos como para seguir jugando, así que quien
declina de verdad no aparece promediando poco a los 36 — aparece fuera de la
NBA, y desaparece del cálculo.

La corrección es el **método delta** (comparar a cada jugador consigo mismo entre
temporadas consecutivas). No está implementado, así que la función lleva el aviso
en su docstring y **ningún endpoint la expone**. Documentado en
`CAPABILITIES.md` §3.

Es preferible una función marcada como no fiable que un endpoint que devuelva
"a tu edad esto es normal" apoyado en una curva sesgada.

---

## 🔵 Estado y siguientes pasos

El sistema está **completo y funcionando de punta a punta**. Levantarlo:

```bash
uv run uvicorn nbastats.api.main:app --reload    # API en :8000
cd web && npm run dev                            # interfaz en :5173
```

Candidatos para lo siguiente, por valor:

1. **Método delta para las curvas de edad** — desbloquea la pregunta más
   valiosa del proyecto: distinguir "está en declive" de "tiene 34 años y le
   pasa lo que a todos".
2. **Comparador de jugadores** — la quinta vista del plan, la única que falta.
3. **Box scores por partido** (~6.600 peticiones, ~1,3 h) — añade `started` y
   `dnp_reason`, y con ellos el split titular/banquillo.
4. **Play-by-play** — elimina casi todo el bloque A de `CAPABILITIES.md`:
   clutch, quintetos, rendimiento por cuarto.
