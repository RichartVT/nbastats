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
| 7 | Perfiles de jugador y equipo, datos de plantilla y clasificación | ✅ Completa |
| 8 | Análisis de equipo y comparador de jugadores | ✅ Completa |
| 9 | Pantalla de jugadores: filtros, situación, orden encadenado | ✅ Completa |
| 10 | Por debajo del partido: cuartos y contexto de partido | ✅ Completa |
| 11 | Equipos: de dónde salen los puntos, récord previo, estabilidad | ✅ Completa |
| 12 | Play-by-play completo | ✅ Completa — 3.251.908 eventos, 6.602/6.602 |
| 13 | Motor de resultado esperado | ✅ Completa — con resultado negativo documentado |
| 14 | Ratings ajustados por rival | ✅ Completa — 65,5 % fuera de muestra |
| 15 | Probabilidad y calibración | ✅ Completa — calibración dentro del ruido |
| 16 | Ratings y pronóstico en pantalla | ✅ Completa — `/pronostico` |
| 17 | Auditoría: el simulador ahora usa el modelo validado | ✅ Completa — coeficientes persistidos |
| 18 | Prior entre temporadas + triples, historial y escudos | ✅ Completa — 4.910 partidos con pronóstico |
| 19 | Índice de ausencias | ✅ Completa — 21,4 pp de recorrido, 13.204/13.204 |
| 20 | `/expected` y `/stability` en pantalla | ✅ Completa — residuo 3,2e-14 |
| 21 | Deuda de mantenimiento | ✅ Completa — `daily` completo, obsolescencia visible, oxlint a cero |
| 22 | Calidad de tiro desde el play-by-play | ✅ Completa — **resultado negativo**, línea cerrada |
| 23 | Curva de edad por método delta | ✅ Completa — sesgo corregido y medido |
| 24 | Titularidad y DNP | ✅ Completa — 6.602/6.602, invariante al dígito |
| 25 | El techo del pronóstico, medido | ✅ Completa — está en el límite del ruido |

**Números:** 6.602 partidos · 172.477 filas jugador-partido (140.932 apariciones + 31.545 DNP) · 481.863 filas
jugador-partido-cuarto · **3.251.908 eventos de play-by-play** · 53.534 filas de
marcador por periodo · 1.030 jugadores con biografía completa · 5 temporadas
(2021-22 → 2025-26) · 523 tests · 15 migraciones · **844 MB**.

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

### 2026-08-23 · Fases 7 y 8 — Perfiles, equipos y comparador

Reequilibrio pedido por el usuario: la aplicación giraba en torno a los splits
condicionales, que son una función más y no el esqueleto. Ahora la ficha de
jugador ordena identidad → rendimiento reciente → trayectoria → splits.

**Datos nuevos, casi gratis.** Dorsal, estatus, experiencia, equipo actual y
draft ya venían en la respuesta de `CommonPlayerInfo` que la ingesta descargaba
y tiraba: cero peticiones extra. Fichas de equipo (30), plantillas de las 5
temporadas (2.605 filas) y clasificación (150). Las fotos y logos se enlazan al
CDN y se derivan del id, sin guardar URLs: coste en disco cero.

**La clasificación resultó trivial**, al contrario de lo que advertí en el plan.
`LeagueStandingsV3` devuelve `PlayoffRank` con los desempates oficiales ya
aplicados. Cinco llamadas.

#### Cuatro correcciones que solo aparecieron al comparar con la realidad

1. **Los puestos de liga usaban un umbral inventado** (20 partidos, 15 minutos)
   y no cuadraban con ninguna fuente: Dončić salía 30º en rebotes cuando todas
   publican 22º. Sustituido por la regla oficial de la NBA —58 partidos, el 70%
   de la temporada—. Ahora coincide exacto en puntos, rebotes y asistencias.
   Los porcentajes siguen difiriendo porque la NBA los cualifica por mínimo de
   intentos, no de partidos; documentado en código y visible en la interfaz.

2. **Se estaba tirando la ronda de playoffs.** La fuente distingue
   "NBA Finals" de "West First Round" y trae el número de partido en el
   sublabel. Ahora muestra "Final de conferencia Oeste · G7". Al revisar las 55
   combinaciones reales aparecieron tres trampas: el formato cambia entre
   temporadas ("East - Conf. Finals" → "East Conf. Finals"), las etiquetas
   llevan patrocinador que cambia cada año, y "Conf. Semifinals" contiene
   "Finals" — el mismo error de subcadena que ya mordió con "Quarterfinal".

3. **Las líneas del comparador se mantenían planas durante meses.** Era el
   verano: `connectNulls` tendía un puente recto entre el último partido de
   junio y el primero de noviembre. Ahora cada jugador lleva su propia serie y
   la línea se parte en los parones de más de 40 días.

4. **Los bigotes del intervalo no se dibujaban.** Estaban en el DOM con
   `transform: scaleX(0)`: Recharts los anima desde cero durante 400 ms.
   Desactivada — en un gráfico estático esa animación no aporta nada y se lee
   como si el intervalo estuviera cambiando.

#### Un problema de diseño que destapó el propio análisis

La pantalla de equipo analizaba una sola temporada. Con 41 partidos en casa,
**ni siquiera la ventaja de campo alcanza significación**:

```
OKC, rating neto local/visitante
  solo 2025-26 (n≈41):     11,50 vs 10,79   q=0,84    -> ruido
  las 5 temporadas (n≈205): 7,52 vs  1,90   q=0,0007  -> REAL

contraste de cordura, 30 equipos × 5 temporadas:
  +1,93 en casa contra −1,93 fuera  (la ventaja de campo documentada)
```

Es la mejor validación que ha tenido la capa estadística: el sistema no
responde "sin patrón" por defecto — se niega a afirmarlo sin potencia y lo
detecta cuando la hay, con la magnitud correcta. El análisis pasa a tener su
propio alcance, separado del de la plantilla y el calendario, con las 5
temporadas por defecto.

#### Una tensión de diseño que no tiene solución limpia

La guía de visualización exige etiquetas directas a partir de cuatro series,
pero también prohíbe que las etiquetas se solapen — y cuatro jugadores con
rendimientos parecidos terminan la línea casi a la misma altura. Se resolvió
ordenando la leyenda por el valor final: cumple el objetivo (que la identidad
no dependa solo del color) sin provocar la colisión que el mismo documento
avisa de evitar. Queda anotado como desviación deliberada.

---

## Fase 10 — Por debajo del partido: cuartos y contexto

Primera vez que el proyecto guarda algo con granularidad **inferior al partido**.
Cierra la primera entrada del bloque A de `CAPABILITIES.md`: "¿cómo rinde en el
cuarto cuarto?".

### El hallazgo que abarató la fase 350 veces

El plan estimaba ~6.600 peticiones y 1,3 h para el desglose por cuarto, porque
el camino evidente era `BoxScoreTraditionalV3`, que acepta
`start_period`/`end_period` y cuesta **una petición por partido y por periodo**
— 26.400 en realidad, 7-11 horas.

Pero `PlayerGameLogs` acepta `Period`, y devuelve la **temporada entera**
restringida a un periodo en una sola llamada. Las cinco temporadas: **93
peticiones y cinco minutos.**

No se dio por bueno sin comprobarlo, porque la API de la NBA ignora parámetros
en silencio con cierta frecuencia y una respuesta ignorada habría devuelto
cuatro veces el total del partido sin avisar. La comprobación: sumar los
periodos 1-4 de 2024-25 y contrastar contra el total. Cuadró en 25.930 de
26.304 jugador-partido (98,6%), y los 374 restantes resultaron ser exactamente
los partidos con prórroga, a los que les faltaban los periodos 5 y 6.
Verificado uno a uno.

**La lección, que es general:** antes de pagar una pasada por partido, mirar si
el endpoint masivo admite el filtro. Lo mismo vale para `MeasureType`, que
admite `Scoring`, `Misc` y `Usage` — tres familias avanzadas a ~15 peticiones
cada una en vez de 6.600.

### Cuadre: 140.932 de 140.932, cero descuadres

El criterio de aceptación no fue opcional: `verificar_cuadre()` corre al
terminar cada carga y compara la suma de los periodos contra
`player_game_stats`, que ya estaba validado contra NBA.com. Puntos, rebotes,
asistencias, tiros intentados, pérdidas y minutos (±2 s por el redondeo de la
fuente). **Cero descuadres en las seis comprobaciones.**

Si los cuartos no suman el partido, o falta un periodo o la API ignoró el
parámetro — y en los dos casos el dato no vale.

### El cuarto es una dimensión, no una pantalla

Se añadió `Dimension.PERIOD` al catálogo en vez de construir un endpoint nuevo.
Así hereda gratis el encogimiento bayesiano, Benjamini-Hochberg, el semáforo de
fiabilidad, el gráfico de puntos con bigotes y el menú del frontend. La única
concesión: `get_split_groups` se desvía a otra tabla cuando la dimensión es el
cuarto, porque en `mv_player_game_rates` una fila **es** un partido entero y un
partido no tiene "cuarto".

El resultado en Jokić enseña por qué merecía la pena montarlo sobre el motor que
ya existía:

| | n | media | IC 95% | fiabilidad |
|---|---|---|---|---|
| 1er cuarto | 357 | 8,12 | 7,67 – 8,56 | alta |
| 2º cuarto | 357 | 5,55 | 5,20 – 5,90 | alta |
| 3º cuarto | 352 | 8,13 | 7,70 – 8,56 | alta |
| 4º cuarto | **295** | 6,02 | 5,60 – 6,44 | alta |
| 1ª prórroga | 22 | 6,09 | 4,03 – 7,51 | media |
| 2ª prórroga | 2 | 6,16 | −22,4 – 28,4 | baja |

**n=295 en el cuarto cuarto frente a 357 en el primero**: no juega todos los
últimos cuartos. Los minutos lo confirman (10,6 / 7,0 / 10,9 / 7,2), y la
diferencia de puntos es sobre todo una historia de minutos. Por eso los minutos
son una estadística seleccionable de la dimensión y el aviso lo dice. La 2ª
prórroga, con n=2, sale sola marcada como no fiable.

### Sin tasas por cuarto, a propósito

`player_period_stats` guarda totales y segundos, nada más. Extrapolar a 36
minutos desde los 4 que alguien jugó en un tercer cuarto produce los mismos
disparates que el `pace` de jugador que motivó ampliar el alias `Rate`. Pedir
`pts_per_36` con dimensión "cuarto" devuelve un 422 que enumera las válidas, y
el menú del frontend filtra las tasas al cambiar de dimensión — cayendo a puntos
si había una seleccionada, en vez de dejar la pantalla en error.

### Contexto de partido: cuatro huecos con una petición

`BoxScoreSummaryV3` (V3 y no V2: la V2 avisa en su propio constructor de que
faltan datos desde 2025-04-10, lo que cubre el final de 2024-25 y toda 2025-26)
trae en una sola llamada el marcador por cuarto, la asistencia, el pabellón, los
árbitros y los periodos de prórroga. 6.602 peticiones, 1,3 h.

Rellena `games.attendance` y `games.arena_name`, que existían desde el esquema
inicial y valían NULL siempre. Cuadre: **13.198 de 13.198 equipos**, la suma de
sus cuartos es exactamente `team_game_stats.pts`.

**Sobre las prórrogas, una nota honesta.** `ot_periods` se venía infiriendo con
`round((MIN − 48) / 5)`. Se guardó el valor inferido antes de sobrescribirlo
para poder comparar: **coincidió en los 6.579 partidos, sin una sola
diferencia.** La heurística no estaba mal. Lo que cambia es que ahora el dato se
lee en vez de deducirse, que es la política del proyecto desde el bug de
"Quarterfinal" — pero conviene no vender como arreglo lo que fue una
confirmación.

### Tres partidos sin resumen en la fuente

`0022500259`, `0022500260` y `0022500261` (19-11-2025) devuelven el resumen con
todos los campos a `null`; el parser de `nba_api` revienta al leerlos. No es un
fallo de red ni nuestro: la NBA no tiene esos datos. Son 3 de 6.602 (0,045%).

Se documenta el hueco en lugar de rellenarlo, igual que con los 2 partidos en
sede neutral de 2022-23. El marcador por cuartos de esos tres partidos no
existe, y la ficha lo dice explícitamente en vez de pintar una tabla de ceros.

**Esto destapó un fallo real del cliente**: `_call` reintentaba ante *cualquier*
excepción, incluidos los errores de forma. Cinco intentos con espera creciente
sobre una respuesta que nunca va a cambiar son 30 segundos tirados por partido.
Ahora `AttributeError`, `KeyError`, `TypeError` e `IndexError` no se reintentan:
esos delatan que la respuesta tiene otra forma, y eso no se arregla insistiendo.
Los tres partidos pasaron de tardar 90 segundos a 2,5.

### Otro arreglo del cliente

`_extract_rows()` solo entiende el formato `resultSets` clásico. Los endpoints
V3 devuelven un JSON anidado, así que usarlos obligaba a llamar a `_throttle()`
a pelo y **quedarse sin reintentos** — inaceptable en un bucle de 6.600
peticiones, donde un corte de red pasajero tira la pasada entera. Se separó
`_call_raw()` (ritmo + reintentos, sin interpretar) de `_call()` (que además
extrae las filas).

### Récord con el que se llega al partido

Añadido como columna derivada en `derive.sql`, junto a `rest_days`, porque
depende de todos los partidos anteriores del equipo: calcularlo en la ingesta
daría resultados distintos según el orden de carga.

`COUNT(*) FILTER (WHERE won) OVER (... ROWS BETWEEN UNBOUNDED PRECEDING AND
1 PRECEDING)`. El `1 PRECEDING` es lo que impide que el partido se cuente a sí
mismo — sin él, todo equipo llegaría a su debut con un 1-0. La partición incluye
`season_type`: arrastrar el récord regular a un séptimo partido de final daría
un "58-24" que no es con lo que se llega a ese partido.

Validación: el récord tras el último partido de cada equipo coincide con
`team_standings` en los **30 de 30** equipos de 2024-25.

Es el dato que convierte un resultado en una historia. "Ganó por 20" dice poco;
"el 9-11 ganó por 20 al 13-7" lo dice todo.

### Lo que se pintó en la aplicación

- **Marcador por cuartos** en la ficha de partido, con las prórrogas etiquetadas
  P1/P2 y el ganador de cada cuarto resaltado.
- **Récord al llegar**, bajo el nombre de cada equipo.
- **Vista "Por cuartos"** en el box score, con los puntos de cada jugador en
  cada periodo. Un periodo que el jugador no jugó se pinta como `·` y no como
  `0`: son cosas distintas y el `0` sería mentira.
- **Árbitros con nombre**, pabellón y asistencia en la cabecera.
- **"Cuarto" como dimensión de splits** en la ficha de jugador, con su semáforo.

Detalle que resultó importante: los periodos de la vista por cuartos se calculan
desde el box **por jugador**, no desde el marcador de equipo. Son dos cargas
independientes, y gracias a eso los 3 partidos sin resumen conservan su
desglose por cuarto.

### Lo que se aprendió para las fases siguientes

- **El play-by-play trae las coordenadas de tiro** (`xLegacy`, `yLegacy`,
  `shotDistance`): los 183 tiros de campo de un partido de muestra las traían,
  los 183. `ShotChartDetail` sobra, y con él una pasada entera de ~3.000
  peticiones que `CAPABILITIES.md` §5 daba por necesaria.
- **Volumen real del play-by-play: 525 eventos por partido**, no ~450. Son
  ~3,5 M filas para las cinco temporadas.
- **Trampa esperando en la fase de titularidad**: `BoxScoreTraditionalV3`
  devuelve también a los jugadores que no jugaron. Cargarlos añade ~53.000 filas
  a `player_game_stats` y rompe en silencio la definición de `games_played` de
  `mv_player_season`, que es `COUNT(*)` precisamente porque hoy la fuente solo
  trae a los que aparecieron. Los promedios de todos los jugadores de rotación
  corta se hundirían. La corrección
  (`COUNT(*) FILTER (WHERE dnp_reason IS NULL)`) tiene que ir en la misma
  migración, con contraste antes/después contra NBA.com.

---

## Fase 11 — Equipos: de dónde salen los puntos, y qué se repite

El proyecto gira hacia los equipos y hacia una pregunta nueva: *"este equipo
debió ganar, ¿por qué perdió?"*.

### Lo que se midió antes de diseñar nada

Ninguna de estas cifras es una estimación; todas salen de consultar la base
antes de escribir una línea de motor.

**El listón del pronóstico.** Gana el local el **55,3 %** de las veces (6.136
partidos, sin sede neutral). Gana el de mejor récord el **64,4 %** (4.539
partidos, desde el partido 20). Cualquier modelo que no bata el 64,4 % no vale
nada, y el techo realista está en 68-71 %. Escrito antes de empezar, para no
tener que justificarlo después.

**Cuánta suerte hay.** La desviación típica del % de triple de un equipo en un
partido es de **8,2 puntos porcentuales**; traducido a puntos, la de "triples
por encima o por debajo de su propia norma" es de **8,5 puntos**. Los equipos
promedian +2,8 de ese factor en sus victorias y −2,8 en sus derrotas, sobre un
margen medio de 12,4.

**Cuántas anomalías hay.** El 25,1 % de los partidos se decide por ≤5 puntos. El
**17,9 %** de los equipos con mejor eFG% pierde. Solo el **0,4 %** pierde
ganando los cuatro factores de Oliver: unos 25 partidos en cinco temporadas.

**Las ausencias, gratis.** Cruzando los minutos habituales de la rotación con
quién jugó cada partido sale un gradiente monótono de **24 puntos porcentuales**
en victorias, del 63,9 % con la plantilla entera al 40,1 % con 100+ minutos
habituales fuera. Cero peticiones nuevas.

### De dónde salen los puntos: 15 peticiones

`TeamGameLogs(MeasureType="Misc")` da los puntos en la pintura, de contraataque,
tras pérdida y de segunda oportunidad —**propios y del rival**— para una
temporada entera en **una** petición. Se integró como tercer `MeasureType` de la
carga masiva que ya existía, así que `daily` lo mantiene solo.

Cobertura 13.204/13.204, y una comprobación que da confianza: los puntos en la
pintura que la fila de un equipo atribuye al rival coinciden con los propios de
la fila del otro equipo en **los 13.204 casos**. Dos registros independientes de
la misma fuente que concuerdan.

**Hallazgo colateral.** El `upsert()` genérico pone a NULL toda columna que no
venga en la fila —por eso `rest_days` se pasaba explícito con un comentario— así
que las columnas nuevas y `wins_before`/`losses_before` se pasan también
explícitas. Sin eso, cada recarga las habría borrado en silencio hasta el
siguiente `refresh`.

### Récord con el que se llega al partido

Columna derivada en `derive.sql`, junto a `rest_days`, porque depende de todos
los partidos anteriores del equipo. `COUNT(*) FILTER (WHERE won) OVER (... ROWS
BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)`; el `1 PRECEDING` impide que el
partido se cuente a sí mismo. La partición incluye `season_type`, para que un
séptimo partido de final no muestre el 58-24 de la fase regular.

Validado: el récord tras el último partido coincide con `team_standings` en los
**30 de 30** equipos.

### `analysis/stability.py`: medir antes de afirmar

El plan original **daba por sentado** qué componentes son suerte y cuáles
habilidad. Eso es una opinión. El módulo nuevo descompone la varianza entre
equipos —reutilizando `_estimate_tau_squared`, el mismo método de los momentos
que sostiene el encogimiento de los splits— y devuelve

    k = varianza intra / varianza real entre equipos

que se lee en partidos: cuántos hacen falta para que la media propia pese la
mitad. La tabla completa está en `CAPABILITIES.md` §5. El contraste que sostiene
todo el motor:

| | k | Peso con 82 partidos |
|---|---|---|
| Triples que **concedes** | 8 | 0,91 |
| Que **entren** | 150 | 0,35 |

Un equipo controla el volumen que concede casi veinte veces mejor que el
acierto. Y un resultado que contradecía lo esperado: el **acierto de 2 concedido
sale en k=17**, o sea habilidad clara. Proteger el aro se repite; defender el
triple, no.

---

## Fase 12 — Play-by-play

3.251.908 eventos, 6.602/6.602 partidos, **cero fallos en la fuente**. 6.602
peticiones en **1 h 11 min** — bastante menos que las ~3 h estimadas. La tabla
ocupa 576 MB y la base pasa de 233 MB a 844 MB.

### Dos errores de diseño que solo aparecieron cargando

**La clave primaria estaba mal.** Se asumió `(game_id, action_number)`. Los
eventos LIGADOS comparten `action_number`: un tiro fallado y el tapón que lo
causó llegan con el mismo número y el mismo reloj, y solo `action_id` los
separa. Medido: 577 eventos con 577 `action_id` distintos y 543
`action_number`. La migración se reescribió a mano para recrear la tabla —
estaba vacía, así que el esquema quedó como si hubiera nacido bien— y
`action_number` se conservó, porque es justo lo que agrupa los eventos ligados.

**`personId` no siempre es un jugador.** En los tiempos muertos lleva el id del
EQUIPO; en las técnicas, el del ÁRBITRO (aparecieron 320, 544 y 739 en un solo
partido). Los tres violaban la clave ajena. Ahora se validan contra el censo de
`players` y lo que no lo sea va a NULL; su identidad sigue viva en
`description`.

Los dos tienen test. La lección se repite por tercera vez en el proyecto: el
esquema estrecho hace de test, y las suposiciones sobre la forma de la fuente
solo se confirman cargándola.

### El cuadre que parecía roto y no lo estaba

La comprobación automática dio 6.598 de 6.602. Al mirar los cuatro, el fallo era
**de la comprobación**: tomaba el marcador del último evento, y los eventos
posteriores a la última canasta arrastran el marcador anterior.

```
479  Hield 24' 3PT    122-112   <- el bueno
480  Instant Replay   119-112   <- revierte
481  End of Period    119-112   <- y aquí miraba la comprobación
```

El marcador nunca decrece dentro de un partido, así que lo correcto es el
MÁXIMO. Con esa corrección: **6.602 de 6.602 exactos**, incluido el partido que
aparentaba estar truncado 52 puntos. Documentado en el docstring de
`verificar_marcador()` para que a nadie le vuelva a parecer que hay cuatro
partidos rotos.

### `ShotChartDetail` ya no hará falta nunca

Las coordenadas (`x_legacy`, `y_legacy`, `shot_distance`) venían dentro del
play-by-play. `CAPABILITIES.md` lo contaba como una ampliación aparte de ~3.000
peticiones; se ahorró la pasada entera.

### Lo que quedó descartado, y por qué

Se evaluó bajar los cambios de liderato, la máxima ventaja y las veces empatado
de `BoxScoreSummaryV2`. Comprobado: su bloque `OtherStats` viene **vacío en
2025-26** (funciona en 2022-23), y la V3 no los trae — su bloque `statistics` es
literalmente `{"dummyKey": "dummyValue"}`. Habrían sido 6.602 peticiones para un
dato ausente en el 30 % de los partidos. Los tres se derivan del play-by-play,
completos, porque el marcador viaja en cada evento.

---

## Fase 13 — Motor de resultado esperado, y su resultado negativo

`analysis/expected.py`: dado un partido, cuántos puntos cabía esperar con **ese**
volumen de tiro y el acierto normal, y a qué se debe la diferencia con lo que
pasó.

### Lo que funciona: el desglose cierra exacto

Se mantiene el volumen —cuántos triples se tiran y cuántos se conceden se mide
en k=3 y k=8, es decisión— y se sustituye solo el **acierto**. Al dejar el
volumen fijo, cada término es lineal:

    suerte_3 = 3 · FG3A · (fg3% − norma)

Sin términos cruzados, sin Shapley, sin discutir el orden de sustitución. Y como
los puntos son `2·FGM + FG3M + FTM` por identidad —comprobado en las 13.204
filas de equipo y las 140.932 de jugador, sin una excepción— la suma de los
componentes **es** la diferencia entre el margen real y el esperado.

Verificado sobre los 6.150 partidos de temporada regular con normas
leave-one-out: **peor residuo sin explicar, 0,000000000000 puntos.**

### Lo que NO funciona: "debió ganar" no sobrevive a su propia prueba

La prueba decisiva, fijada antes de mirar el resultado: *si el margen esperado
mide mejor la fuerza de un equipo que el margen real, la media de los primeros k
partidos debe predecir el resto de la temporada mejor.* Sobre 150
equipos-temporada, RMSE fuera de muestra:

| k | Margen real | Solo se normaliza el rival | Solo el triple, ambos lados | Solo el triple concedido |
|---|---|---|---|---|
| 10 | **5,003** | 5,371 | 5,104 | 5,029 |
| 20 | 4,300 | 4,695 | 4,333 | **4,215** |
| 30 | 4,261 | 4,577 | 4,357 | **4,196** |
| 41 | **4,254** | 4,704 | 4,642 | 4,344 |

La primera versión —sustituir el acierto de los dos equipos por la norma de
liga— perdía en los cuatro cortes, y con razón: tira habilidad real, porque la
propia tabla de estabilidad dice que el acierto de 2 (k=16) y el de libres
(k=21) **son** habilidad. Corregido eso, la mejor variante gana por un 1-2 % en
dos cortes y pierde en los otros dos. Con 150 unidades, eso es ruido.

**Conclusión: el margen esperado no es un mejor estimador de la fuerza de un
equipo que el margen real.** El criterio decía que si a k=10 y k=20 no gana, no
se publica como veredicto. A k=10 pierde.

### Qué se hace con eso

Se separan dos afirmaciones que estaban mezcladas:

1. **"De los 4 puntos de derrota, el acierto en triples del rival por encima de
   su norma aporta −12."** Es aritmética exacta, verificable a mano y útil. Se
   publica.
2. **"Debió ganar."** Es un veredicto sobre el mérito, y para sostenerlo hacía
   falta que el margen esperado midiera mejor la fuerza. No la mide. **No se
   publica como veredicto.**

La pantalla dirá de dónde salieron los puntos y cuánto pesó cada factor, sin
decidir quién merecía ganar. Es el mismo precedente que la curva de edad: existe
en código, no tiene endpoint, y el motivo está escrito.

### El continuo por componente tampoco lo salva

Quedaba una vía: en vez de sustituir un componente del todo o nada, encogerlo
hacia la liga con **su** peso `w(n) = n/(n+K)`, usando los `K` medidos. Es el
estimador estadísticamente correcto y no se había probado.

Sobre equipos-temporada seguía alternando de signo (+1,3 %, −0,4 %, +0,8 %,
−4,1 %), así que se rehízo la prueba **a nivel de partido**, donde hay potencia
de verdad: qué estimador de fuerza acierta más veces el ganador del siguiente
partido, con walk-forward estricto y ambos equipos con ≥20 partidos previos.

| Estimador | Acierto | Muestra |
|---|---|---|
| Margen real medio | **64,12 %** | 4.596 partidos |
| Continuo por componente | 63,69 % | 4.596 partidos |

Diferencia **−0,44 pp** sobre 516 partidos discordantes: por debajo del umbral
de ruido de ±1,0 pp. Los dos estimadores coinciden en el 88,8 % de los partidos.

**Conclusión firme: normalizar el acierto no mejora la estimación de fuerza, ni
del todo, ni por partes, ni con el peso correcto.** El simple diferencial de
puntos ya lo hace igual de bien. Se probaron cinco formulaciones y ninguna
supera al margen real.

Es coherente con lo que se sabe del baloncesto —el diferencial de puntos es un
predictor muy difícil de batir con ajustes de box score— pero aquí está medido
sobre estos datos y no citado de memoria.

**Y deja una pista para la fase de pronóstico:** el margen real medio acierta el
64,12 %, prácticamente lo mismo que la línea base de "gana el de mejor récord"
(64,4 %). Para batir ese listón no hay que tocar el acierto de tiro; hay que
meter lo que ninguno de los dos tiene — **ajuste por calidad del rival**,
localía y descanso.

---

## Fase 14 — Ratings ajustados por rival

`analysis/ratings.py`. Una fila por equipo y partido:

    anotados_por_100 = μ + O(equipo) − D(rival) + h·(local ? +1 : −1)

Mínimos cuadrados con **filas aumentadas** para la regularización, en vez de un
optimizador: forma cerrada, se ve exactamente qué columnas se penalizan —las de
equipo sí, `μ` y la localía no— y no hay nada que pueda dejar de converger.

**λ no se busca a ciegas: es la `k` medida.** `stability.py` sobre estos datos da
k≈12 para el rating ofensivo (SD entre partidos 11,2; diferencia real entre
equipos 3,27) y k≈15 para el defensivo. λ ES esa k, así que el único parámetro
libre del modelo ya venía medido.

### Validación contra ligas sintéticas

Con equipos de fuerza conocida se recupera la verdad: correlación **0,96** en
ataque y **0,92** en defensa, y la localía estimada en 1,87 frente a 2,0 reales.

### Resultado del backtest walk-forward

Reajuste por fecha, usando solo partidos anteriores; ambos equipos con ≥20
partidos previos; sin sedes neutrales. 4.596 partidos.

| Método | Acierta el ganador |
|---|---|
| Gana el local | 54,42 % |
| Gana el de mejor récord | 64,25 % |
| Diferencial de puntos sin ajustar | 64,12 % |
| **Ridge ajustado por rival** | **65,47 %** |

McNemar sobre los pares discordantes:

| Contra | Diferencia | p |
|---|---|---|
| Gana el local | +11,05 pp | <0,0001 |
| Diferencial de puntos | +1,35 pp | **0,030** |
| Gana el de mejor récord | +1,22 pp | **0,063** |

**Lectura honesta.** Bate al diferencial de puntos de forma significativa, y ahí
queda demostrado que el ajuste por rival aporta algo real. Contra la línea base
del récord se queda en **p=0,063**: por encima, pero no distinguible del ruido al
5 %. El criterio del plan era batir el 64,4 %; lo bate en el número, no con
holgura estadística.

No se toca nada más para "arreglar" ese p-valor: seguir probando variantes hasta
cruzar el 0,05 es exactamente la pesca de patrones que este proyecto existe para
no hacer. El siguiente paso —probabilidades y calibración— estaba en el plan
desde antes de ver este número, y usa mucha más información que el signo del
margen, así que es la comparación que decide de verdad.

### `league_mean` no es lo que parece

Un test falló al no recuperar la media del proceso generador (110,8 estimada
frente a 115 real). **El fallo era del test.** `O` y `D` solo están determinados
hasta una constante, la regularización los centra en cero, y `league_mean`
absorbe su media. Comprobado: `league_mean` coincide **exactamente** con la
anotación media de las filas. Es la parametrización útil —lo que devuelve es la
anotación real de la liga— pero quedó documentado, porque quien lea el
coeficiente esperando "el μ del modelo" va a leer otra cosa.

---

## Fase 15 — Probabilidad y calibración

`analysis/forecast.py` y `analysis/calibration.py`. Primer uso real de
`statsmodels`, que llevaba declarado en `pyproject.toml` desde el principio sin
importarse en ningún módulo.

### Dos señales de acuerdo, otra vez

La probabilidad sale por **dos rutas independientes** y solo se publica si
coinciden: una regresión logística sobre el resultado, y una regresión lineal
sobre el margen que da μ y σ y de ahí `P = Φ(μ/σ)`. La primera solo ve el signo;
la segunda ve la magnitud. Es el mismo criterio que `analyze_trend` aplica
exigiendo Mann-Kendall e intervalo antes de declarar una tendencia.

Cinco variables y ni una más: diferencia de rating, localía, descanso y
back-to-back. Con ~4.500 partidos y σ≈13 puntos de ruido irreducible, cada
variable extra compra una milésima de log-loss y vende sobreajuste.

### Entrenamiento sin ver el futuro, en dos niveles

Los ratings se reajustan **por fecha** con partidos anteriores, y el modelo de
probabilidad se entrena **solo con temporadas anteriores** a la que se evalúa.
La primera temporada no se puntúa porque no tiene con qué entrenarse.

### Resultado sobre 3.674 partidos fuera de muestra

| Métrica | Modelo | Siempre local | Mejor récord |
|---|---|---|---|
| Acierto | **65,84 %** | 54,55 % | 64,64 % |
| Brier | **0,2128** | 0,2479 | — |
| Log-loss | **0,6132** | 0,6890 | — |
| Brier Skill Score | **0,1417** | 0 | — |

Tres de las cuatro cifras caen **dentro del rango que se declaró honesto antes
de medir** (Brier 0,205-0,215; log-loss 0,600-0,620; BSS 0,13-0,17). La
precisión se queda justo por debajo del +1,5 pp previsto.

Contra la línea base del récord: **+1,20 pp, p=0,083** (McNemar, 329 frente a
285 discordantes). Igual que en la fase 14, no llega al 5 %. Y no se toca nada
para empujarlo: la línea base del récord **no produce probabilidades**, así que
la comparación en precisión es la menos favorable posible para el modelo y aun
así gana. Donde aporta algo que el récord no puede dar es en las tres filas de
abajo.

### La calibración

| | |
|---|---|
| Pendiente de Cox | **1,06** (perfecto = 1) |
| Intercepto | **−0,00** (perfecto = 0) |
| ECE | **0,0117** |
| Suelo de ruido | 0,0208 |

**El desajuste está por debajo del suelo de ruido de la propia muestra**: con
~367 partidos por tramo no se puede distinguir de una calibración perfecta. Y
los **diez tramos** contienen la probabilidad predicha dentro del intervalo de
Wilson de la frecuencia observada:

```
     tramo      n    dice    gana           IC 95%
   0.2-0.3    271   0.252   0.203  [0.159,0.255]
   0.4-0.5    594   0.453   0.466  [0.427,0.507]
   0.6-0.7    655   0.649   0.647  [0.610,0.683]
   0.7-0.8    481   0.745   0.767  [0.727,0.803]
   0.9-1.0     40   0.921   0.950  [0.835,0.986]
```

Cuando dice 74,5 %, ganan el 76,7 %. Esa es la propiedad que hace que las
probabilidades signifiquen lo que dicen, y la que ninguna línea base puede dar.

**El aviso va delante de la tabla, no detrás:** con ~367 partidos por tramo el
error típico es de ±4,6 puntos porcentuales, así que no se puede detectar un
desajuste menor de unos 4 pp. Por eso `ece_noise_floor` se publica siempre junto
al ECE — el ECE esperado bajo calibración perfecta **no es cero**.

### Un aviso sobre esta bitácora

La entrada de la fase 14 se escribió con un `replace` que no volvía a poner el
ancla, y se llevó por delante la cabecera de "Estado y siguientes pasos". El
texto siguió ahí, huérfano, hasta que un `grep` no encontró la sección. Queda
anotado porque es el tipo de error que no rompe nada y se detecta tarde.

---

## Fase 16 — A pantalla

`nbastats build-ratings` calcula el walk-forward y lo persiste: **3 segundos**
para 6.140 partidos, 5 temporadas de ratings y 3.674 predicciones. No pide nada
a la NBA. Se guarda en vez de calcularse al vuelo por lo mismo que existen las
vistas materializadas: rápido una vez, inviable por petición.

`game_predictions` es **inmutable por diseño**: una predicción escrita no se
reescribe, y un modelo nuevo es una `model_version` nueva. Sin eso el backtest
"mejora" solo cada vez que alguien toca algo y deja de ser una medición.

### Tres endpoints

| Endpoint | Qué da |
|---|---|
| `GET /ratings` | Los 30 equipos por fuerza, ataque y defensa separados |
| `GET /predict` | Probabilidad con el desglose de dónde sale cada punto |
| `GET /model/backtest` | Métricas, líneas base y los diez tramos de calibración |

Una decisión: `/predict` **lee los coeficientes de una predicción guardada** en
vez de reajustar el modelo. Así la pantalla no puede discrepar del informe de
validación, que es el fallo silencioso más fácil de cometer aquí.

### Una pantalla, tres secciones

`/pronostico`. Simulador arriba, ratings en medio, validación abajo. Es
deliberado que estén juntas: quien mire una probabilidad tiene la calibración
en la misma página, no en un apartado que nadie visita.

El simulador enseña el desglose en barras divergentes centradas en cero —el
cero es "no aporta", y una barra que crece desde la izquierda lo escondería— y
los tres avisos **completos y visibles**, no en un tooltip:

> El intervalo del margen es de ±27 puntos. La varianza de un partido aplasta
> cualquier diferencia de plantilla: un 65 % significa que ese equipo pierde uno
> de cada tres.

Ejemplo real: OKC (+9,42 de neto) contra LAL, con dos días de descanso frente a
back-to-back, da **80 %** y un margen esperado de +11,8 — con un intervalo de
[−15,7, +39,2]. Las dos cifras juntas son la información; la primera sola es
propaganda.

En la tabla de calibración, el aviso va **antes** de la tabla y no después: con
~370 partidos por tramo no se detecta un desajuste menor de ±4,6 puntos
porcentuales, y decirlo primero es lo que impide leer la ondulación como
información.

---

## Fase 17 — El simulador no usaba el modelo que se validó

Una auditoría del proyecto entero encontró un defecto que yo mismo había
introducido en la fase 16, y que es el peor tipo que hay: **visible, silencioso y
tapado por un comentario que afirmaba justo lo contrario.**

`/predict` calculaba el margen así:

```python
descanso = (min(rest_home, 4.0) - min(rest_away, 4.0)) * 0.35
b2b = ((1.0 if b2b_away else 0.0) - (1.0 if b2b_home else 0.0)) * 1.2
margen = diff + ventaja + descanso + b2b
# Mismos coeficientes que el backtest: se leen de una predicción guardada
# en vez de reajustar, para que la pantalla no pueda discrepar del informe.
```

El comentario era **falso**. Lo único que se leía de una predicción guardada era
`margin_sigma`. Los dos multiplicadores estaban escritos a mano, la diferencia de
rating entraba con coeficiente 1,0 implícito, no había intercepto, y la localía
venía del ridge de ratings — otra cantidad distinta de `margin_params["home"]`.

**La causa raíz no era la fórmula, era que no había de dónde leer.**
`build-ratings` ajustaba el `WinModel`, escribía las probabilidades y **tiraba el
modelo**. Los coeficientes no se persistían en ninguna parte. La fórmula paralela
no fue un descuido: fue la única salida que quedaba, y por eso el arreglo no es
corregir los números sino eliminar la posibilidad de que existan dos fórmulas.

### Cuánto erraba

Ajustar y comparar contra lo que había escrito a mano:

| Variable | Ajustado | Literal anterior | Error |
|---|---|---|---|
| `rest_diff` | **0,4235** | 0,35 | −17 % |
| `b2b_diff` | **2,4559** | 1,2 | **−51 %, menos de la mitad** |
| `rating_diff` | **1,1859** | 1,0 implícito | −16 % |
| Localía (`const`) | **1,7055** | no existía | — |
| σ | 13,998 | leída del partido equivocado | — |

En un OKC–LAL con el visitante en back-to-back, la pantalla decía **80,0 %** y el
modelo validado dice **86,0 %**. Seis puntos porcentuales que no venían de los
datos sino de dos constantes inventadas.

### Un segundo fallo en la misma función

`sigma = ultima[0]["margin_sigma"]`, pero `get_predictions` ordena por fecha
**ascendente**: `ultima[0]` era el partido más **antiguo**, o sea la σ del modelo
con menos entrenamiento. Ha dejado de importar porque σ ahora se lee de
`model_runs`, que es su sitio.

### El arreglo

- **Tabla `model_runs`** (`model_version`, `season_id`, `logit_params`,
  `margin_params`, `sigma`, `train_games`, `fitted_at`), escrita por
  `build-ratings`. Los coeficientes de las dos rutas van en JSONB porque son un
  diccionario de tamaño variable, no columnas fijas.
- **`model_from_params()`** en `analysis/forecast.py` reconstruye el `WinModel`.
  Sigue siendo una función pura: recibe diccionarios, no toca la base.
- **`/predict` llama a `probability()`**. No queda ninguna aritmética de
  pronóstico fuera de `forecast.py`.
- **El desglose sale de `margin_params`**, así que las barras suman el margen
  esperado **por construcción**, no porque se haya cuadrado a mano. Sin redondear
  en la respuesta: quien sume los componentes obtiene el margen exacto, y el
  redondeo es cosa de la pantalla.
- **Sede neutral** resta `const` y avisa de que es una extrapolación: no hay
  sedes neutrales en el entrenamiento, y el modelo no puede saber si la localía
  se anula del todo.
- **Aviso si las dos rutas discrepan** más de 3 puntos, con las dos visibles en
  pantalla. El número de portada es su media; si no se ponen de acuerdo, hay que
  poder verlo.
- **Los controles de back-to-back existen ahora en la interfaz.** La API los
  aceptaba desde el primer día y `ForecastPage` no los enviaba nunca, así que la
  fila "Segundo partido en 2 días" valía **siempre 0,00 en pantalla**. Dos
  defectos que se tapaban: aunque el usuario hubiera podido marcarlo, habría
  aplicado el coeficiente equivocado.
- **La pantalla dice qué modelo respondió** y con cuántos partidos se entrenó.

### El test que lo habría cazado

`tests/test_model_persistence.py`, 7 tests. El importante recorre los partidos
guardados y exige que reconstruir el modelo desde `model_runs` reproduzca
`game_predictions.home_win_prob`. Sobre los **3.674 partidos**:

```
peor desviación en probabilidad: 0,0000670745
peor desviación en margen:       0,0010697348
```

La auditoría había fijado 1e-6 como tolerancia y **eso era inalcanzable, por una
razón que conviene dejar escrita**: las probabilidades se guardan redondeadas a 4
decimales, así que el error de redondeo por sí solo llega a 5e-5. La
reconstrucción es exacta —el test unitario contra un modelo en memoria cierra a
1e-12—; el límite lo pone el almacenamiento, no el modelo. Bajar la tolerancia
exigiría guardar más decimales de los que la probabilidad tiene de significado.

Los otros seis prueban que se persisten **todas** las variables y la constante
(un coeficiente que se pierda al guardar daría el mismo fallo por otra vía), que
el desglose suma el margen, y que los coeficientes vienen de un ajuste y no de
constantes — este último falla a propósito si alguien vuelve a escribir un
número a mano.

### Lo que deja como norma

Un comentario que promete coherencia no la produce. **Si dos sitios tienen que
calcular lo mismo, o comparten el código o hay un test que compara sus salidas.**
Es la misma regla que ya se aplica en el resto del proyecto —el desglose que
cierra a cero, la doble ruta que tiene que estar de acuerdo— y aquí faltaba justo
donde el resultado sale a pantalla.

Reajustar tras el cambio no movió ninguna métrica: 65,84 %, Brier 0,2128,
log-loss 0,6132, pendiente de calibración 1,06, ECE 0,0117. Era de esperar y es
la comprobación de que el defecto estaba **solo** en el camino a pantalla: el
backtest siempre había usado el modelo bueno.

---

## Fase 18 — Lo que un equipo se trae del verano

Hasta aquí cada temporada empezaba de cero: con `MIN_PREVIOS = 20`, un equipo no
tenía rating hasta su partido 20, y eso dejaba partidos enteros sin pronóstico.

**Primero, la cifra correcta, porque la del plan estaba mal.** No son 2.466
partidos sin predicción sino **2.928**, y son tres cosas distintas que conviene
no mezclar:

| Causa | Partidos | ¿Lo arregla el prior? |
|---|---|---|
| Toda la 2021-22 | 1.323 | **No** — no hay temporada anterior con la que entrenar |
| Playoffs y play-in | 359 | **No** — excluidos a propósito; el modelo se calibró en regular |
| Arranque de 2022-26 (<20 partidos) | **1.246** | **Sí** |

### Cuánto sobrevive un equipo a su propio verano

Medido sobre las 4 transiciones × 30 equipos (120 pares), regresando el rating
de cada temporada sobre el de la anterior:

| | ρ | pendiente | λ del prior |
|---|---|---|---|
| Ataque | +0,446 ± 0,074 | 0,450 | 16,2 |
| Defensa | +0,517 ± 0,067 | 0,554 | 17,7 |
| Neto | +0,542 ± 0,065 | 0,580 | — |

**La defensa se hereda más que el ataque**, que es lo que cabía esperar: depende
más del sistema y menos de quién tenga la mano caliente. Por eso el prior encoge
cada componente por su propia pendiente y no los dos por la del neto.

Se usan las **pendientes** y no las correlaciones: la pendiente es la predicción
insesgada del año siguiente e incluye la regresión a la media que un equipo
excepcional sufre por serlo.

### Por qué λ del prior es MAYOR que λ contra cero

Parece al revés y no lo es. λ = varianza dentro / varianza entre equipos. Al
encoger hacia cero, lo que hay "entre" es toda la dispersión de la liga (τ²). Al
encoger hacia el prior, lo que queda por explicar es solo τ²(1−ρ²), que es
menor — y λ, que la lleva en el denominador, sube. Dicho en corto: **un prior
informativo merece más peso que la nada.** Sale de los mismos ρ de la tabla, no
de una búsqueda.

La implementación es la que ya estaba: `fit_ratings` regulariza con filas
aumentadas, y basta cambiar su término independiente de `0` a `√λ·prior` para
que minimice `λ(coef − prior)²` en vez de `λ·coef²`. Un equipo que no esté en el
prior —una expansión— sigue encogiendo hacia cero, que para él es lo correcto.

### La prueba, fijada antes de mirar

| Conjunto | n | Acierto | Brier | log-loss | Mejor récord |
|---|---|---|---|---|---|
| **Mismo subconjunto**, sin prior | 3.674 | 65,84 % | 0,2128 | 0,6132 | 64,67 % |
| **Mismo subconjunto**, con prior | 3.674 | 65,81 % | 0,2128 | 0,6134 | 64,67 % |
| Cobertura completa con prior | **4.910** | 65,70 % | 0,2133 | 0,6146 | 63,44 % |
| **Solo los 1.236 nuevos** | 1.236 | **65,37 %** | 0,2146 | 0,6183 | **59,79 %** |

**Sobre los partidos que ya se predecían, el prior no cambia nada** (−0,03 puntos
porcentuales, Brier idéntico a la cuarta cifra). Era el requisito: no empeorar lo
que funcionaba.

**Donde sí cambia algo es donde antes no había nada.** En los 1.236 partidos del
arranque, el modelo acierta el 65,37 % contra el 59,79 % de "gana el de mejor
récord": **+5,6 puntos porcentuales, con p = 6,6e-05** por McNemar sobre 293
pares discordantes (181 a 112). Cuatro veces la ventaja que saca en temporada
madura, y esta vez sí concluyente — lo cual tiene un mecanismo evidente: en
octubre un récord de 3-1 no dice nada, y el prior sí.

**Una pega que hay que publicar:** en esos partidos nuevos la calibración es peor
que en el resto. ECE 0,0455 contra un suelo de ruido de 0,0359, y pendiente 1,22.
Una pendiente mayor que 1 significa **falta de confianza**: el modelo separa
menos de lo que debería y sus extremos están comprimidos. Es la dirección menos
mala de las dos, pero es un desajuste real y no ruido. Sobre el conjunto completo
la calibración sigue dentro del ruido (ECE 0,0174, suelo 0,0180).

### El test que protege esto

`test_el_prior_no_ve_el_futuro` altera el resultado de los últimos 40 partidos y
exige que **ni una sola variable de los partidos anteriores cambie**. Se comprobó
que no es vacuo: introduciendo la fuga a propósito —usar los ratings finales de
la propia temporada como prior— el test falla. Es la única forma de saber que un
test de fuga sirve, porque la fuga no da error: sube las métricas y las deja
mintiendo.

---

## Fase 18b — Tres arreglos de pantalla y una inconsistencia real

**El back-to-back no era una casilla aparte.** En la interfaz había dos controles
independientes, descanso y back-to-back, y se podía pedir "0 días de descanso sin
back-to-back". Eso no existe: los dos salen de la misma resta en `derive.sql`
—`rest_days = (fecha − fecha_anterior) − 1` e `is_back_to_back = (fecha −
fecha_anterior) = 1`—, así que **0 días de descanso ⟺ back-to-back, siempre**.
La pantalla dejaba pedir combinaciones que el modelo nunca vio y respondía
extrapolando. Ahora se deriva del descanso y el estado imposible desaparece en
vez de avisarse.

Que las dos variables sigan en el modelo es correcto y no es redundancia: el
descanso entra lineal y el back-to-back es el **salto** extra de pasar de 1 día a
0. Un local en back-to-back contra un visitante con 1 día pierde 0,42 por el
término lineal y 2,46 más por el salto.

**Triples anotados e intentados**, en el historial de partidos como `3/6` junto a
tiros de campo, y como estadística analizable: `fg3m_per_36` y `fg3a_per_36` son
columnas nuevas de `mv_player_game_rates`. El volumen de triple va como tasa a
propósito — es **decisión**, y la decisión se estabiliza mucho antes que el
acierto (k=3 partidos, medido en la fase 11).

**Historial completo entre los dos equipos** en el simulador, con enlace al
desglose de cada partido. El endpoint `/teams/{a}/vs/{b}` existía desde la fase 8
sin pantalla; es el contexto que un porcentaje solo no da.

**Escudos en el selector.** Un `<select>` nativo solo pinta texto, así que hizo
falta un desplegable propio.

---

## Fase 19 — Índice de ausencias: quién no jugó

La señal más fuerte que quedaba sin usar, y no costó una sola petición.

### El problema: la fuente solo trae a quien apareció

No hay filas de DNP ni motivo, así que "ausente" hay que **deducirlo de un
hueco**: este jugador estaba con este equipo por estas fechas y esta noche no
tiene fila. Lo delicado es el traspaso.

**La regla, y su excepción, que es la que importa.** Un jugador cuenta para un
equipo entre su primera y su última aparición con él. Pero si su última
aparición con ese equipo es también la última de toda su temporada, no se fue a
ningún sitio — se lesionó — y sigue contando hasta el final. Sin esa excepción,
**la lesión de temporada de una estrella desaparecería del índice justo cuando
más pesa.**

Con un guardarraíl: solo se extiende si jugó 10 partidos o más con ese equipo.
Sin él, un contrato de diez días que jugó dos partidos en noviembre contaría como
ausente los otros ochenta.

### El gradiente

| Minutos habituales fuera | Partidos | Victorias | Margen medio |
|---|---|---|---|
| 0–20 | 1.491 | **59,4 %** | +4,2 |
| 20–40 | 2.029 | 57,6 % | +2,5 |
| 40–60 | 2.476 | 55,3 % | +1,6 |
| 60–80 | 2.306 | 50,2 % | +0,2 |
| 80–100 | 1.776 | 46,9 % | −1,3 |
| 100+ | 3.126 | **38,0 %** | −4,4 |

Monótono en los seis tramos **y en las dos columnas**, que es más exigente que
serlo en una.

Controlando por la fuerza de ambos equipos, cada minuto ausente vale **0,0373
puntos de margen** (EE 0,0031, t=11,9, p=2,3e-32): 3,7 puntos por cada 100
minutos. Sube el R² de 0,2268 a 0,2443, **+1,75 puntos de varianza explicada**,
así que no es algo que los ratings ya supieran por otra vía.

### El umbral es una decisión, y se publica su sensibilidad

"Rotación" son los jugadores de 10+ minutos de media — la definición
convencional, elegida **por serlo y no por el resultado que produce**:

| Umbral | Recorrido del gradiente |
|---|---|
| Sin umbral | 15,1 pp (y **no** monótono) |
| ≥6 min | 17,2 pp |
| **≥10 min** | **21,4 pp** |
| ≥15 min | 23,5 pp |

El titular depende de dónde se ponga la raya. Enseñar solo el 23,5 % sería elegir
el número más vistoso; los 24 pp que figuraban en la fase 11 venían de una regla
distinta y quedan corregidos aquí.

### Dónde va, y sobre todo dónde no

- **Explicación: sí, y arriba.** Un equipo sin sus dos mejores no tuvo mala
  suerte: jugó con otro equipo. Va en el contexto previo al partido, junto al
  récord y el descanso, nunca en el bloque de suerte.
- **Backtest del pronóstico: NO, por partida doble.** Que un jugador no aparezca
  en el box score se sabe DESPUÉS del partido; y además los "minutos habituales"
  se calculan con la temporada entera, que incluye partidos posteriores. Hay un
  test, `test_el_indice_no_entra_en_las_variables_del_pronostico`, que falla si
  alguien lo añade a `GameFeatures`.
- **Simulador: sí, como entrada del usuario y como bloque APARTE.** El modelo
  calibrado no se entrenó con esto, así que fundirlo en la probabilidad de
  portada rompería la calibración que sí está medida.

### Comprobaciones

- **Cobertura 13.204/13.204.**
- **Cero contradicciones**: nadie contado como ausente en un partido en el que
  tiene fila. Sale por construcción del `LEFT JOIN … IS NULL`, y aun así se
  comprueba.
- **Minutos habituales contra `mv_player_season`**: 3.296 jugador-equipo-temporada,
  **0** discrepancias en partidos jugados y 0,005 minutos de desviación máxima —
  el redondeo del tipo numérico de la vista. La primera versión de esta
  comprobación daba 23,77 minutos de desviación y **la equivocada era la
  comprobación**: la vista tiene grano (jugador, temporada, equipo) y yo agregaba
  sin el equipo, así que a un traspasado le sumaba los dos destinos.
- **El detalle cuadra con el agregado**: en el partido con más ausencias, la
  consulta que devuelve nombres da 9 y 16 jugadores, exactamente lo que dice la
  columna derivada.

**Un hallazgo colateral que conviene conocer.** 90 equipo-partido (el 0,7 %)
superan los 240 minutos ausentes, que es más de lo que juega un equipo entero.
No es un error: ocurren de media al **89,7 %** de la temporada y son los partidos
en que se reserva a todo el mundo. El índice los detecta bien, pero el tramo de
"100+" mezcla "dos estrellas fuera" con "descansa la plantilla entera".

---

## Fase 20 — Cablear lo que ya estaba construido

1.081 líneas de análisis con 93 tests que ningún endpoint exponía. No hacía
falta escribir motores: hacía falta enchufarlos.

### `/games/{id}/expected` — de dónde salieron los puntos

El desglose que la fase 13 dejó escrito y sin pantalla. Se mantiene el volumen de
tiro y se sustituye solo el **acierto** por la norma del equipo; cada término es
lineal, así que la suma de componentes **es** la diferencia entre el margen real
y el esperado.

**Leave-one-out, y no es un detalle.** La norma de un equipo se calcula sin el
partido que se está explicando. Si lo incluyera, el partido se explicaría en
parte a sí mismo y la "suerte" saldría sesgada hacia cero — y además es la
condición con la que se verificó el motor en su día, así que el endpoint tenía
que respetarla o estaría midiendo otra cosa. Se resuelve con un `FILTER (WHERE
game_id <> :gid)`, que es exacto y no cuesta nada.

**Normas por equipo, encogidas hacia la liga.** Un equipo que tira el 39 % de
tres toda la temporada no "debía" tirar el 36 % de la liga. El encogimiento usa
`shrunk_norm` con priors en intentos derivados de las `k` medidas: el triple es
mucho más ruidoso que el doble (k=150 contra k=16), así que su media propia
necesita más intentos para ganarse el mismo peso.

Verificado sobre 400 partidos al azar por el camino completo del endpoint:
**peor residuo 3,2e-14**, que es aritmética de coma flotante y no un error.

**Lo que NO publica.** El veredicto "debió ganar". La fase 13 lo probó y no
sobrevivió —el margen esperado no predice la fuerza de un equipo mejor que el
margen real— así que la pantalla dice de dónde salieron los puntos y cuánto pesó
cada factor, **sin decidir quién merecía ganar**. `MarginAttribution.flipped`
existe en el módulo y deliberadamente **no se expone**.

### `/stability` y la pantalla "Qué se repite"

La tabla que decide qué es habilidad y qué es la noche, y de la que depende el
motor anterior. Sobre las cinco temporadas:

| Componente | k | Clase |
|---|---|---|
| Triples que **tiras** | 3,0 | Habilidad |
| Ritmo | 5,3 | Habilidad |
| Puntos en la pintura | 6,9 | Habilidad |
| % de rebote ofensivo | 7,4 | Habilidad |
| Triples que **concedes** | 8,1 | Habilidad |
| Puntos de contraataque | 8,5 | Habilidad |
| Puntos de segunda oportunidad | 12,5 | Habilidad |
| eFG% propio | 14,2 | Habilidad |
| Pérdidas por posesión | 15,2 | Habilidad |
| Puntos tras pérdida | 15,2 | Habilidad |
| Tiros libres por tiro de campo | 17,3 | Habilidad |
| eFG% concedido | 24,8 | Habilidad |
| **Acierto en triples** | **47,0** | Mixto |
| **Acierto en los triples que concedes** | **150,5** | Sobre todo azar |

Las dos últimas filas contra la quinta son la idea entera: **conceder triples se
estabiliza en 8 partidos y que entren necesita 150.** Son la misma jugada vista
desde los dos lados, y por eso el motor de resultado esperado mantiene el volumen
y sustituye el acierto. Ya estaba en el docstring del módulo; ahora se puede
comprobar en pantalla y por temporada.

**Y las ocho columnas huérfanas dejan de serlo.** La auditoría anotó que los
puntos en la pintura, de contraataque, tras pérdida y de segunda oportunidad se
ingerían, se migraban, `status` los contaba y no los leía nadie. Aquí se usan, y
dan un resultado que no era obvio: **de dónde salen los puntos de un equipo es
identidad, no ruido** — los cuatro caen entre k=6,9 y k=15,2.

La consulta lee de `team_game_stats` y no de `mv_team_game_rates` porque la vista
sigue sin exponer esas columnas. Queda anotado como deuda, no resuelto.

Lo concedido sale de la fila del **rival** en el mismo partido y no de columnas
`opp_*`, para poder separar el volumen concedido del acierto concedido — que es
justo la distinción que hace falta.

### De paso

`Marcador` estaba definido **dentro** del render de `GamePage`. React lo trataba
como un tipo de componente nuevo en cada render y desmontaba el subárbol entero.
Era la única de las seis advertencias de oxlint con consecuencia real, y estaba
anotada en la auditoría. Sacado fuera.

---

## Fase 21 — Deuda de mantenimiento, antes de que entre la 2026-27

El punto que tenía fecha. Nada de esto costó una petición a la NBA.

### Lo que se iba a desfasar solo

`daily` llamaba a siete cosas y **no a `ingest-pbp` ni a `build-ratings`**. Como
las consultas resuelven la temporada con `COALESCE(:season, MAX(...))` y no había
ninguna marca de obsolescencia, el primer día de la 2026-27 `/ratings` y
`/predict` habrían servido la 2025-26 **como si fuera la actual**, sin error y
sin aviso. El mismo tipo de fallo silencioso que el de la fase 17.

Los dos pasos están añadidos. El de play-by-play solo pide los partidos que
faltan —comprobado: con todo cargado devuelve `{pedidos: 0}` sin tocar la red— y
`build-ratings` no pide nada, es cálculo.

**Y ahora se puede VER si están viejos.** `/ratings` devuelve `fitted_at`,
`last_game_date`, `games_since_fit` e `is_stale`. La definición de desfasado no
es "la temporada no coincide" sino **"hay partidos jugados después del ajuste"**,
que cubre las dos formas de quedarse viejo: que entre una temporada nueva, y que
simplemente lleve semanas sin recalcularse.

Comprobado en los dos sentidos, insertando un partido de la 2026-27 en una
transacción que se deshace: al día no avisa; con un partido nuevo sin reajustar,
`is_stale=true` y la pantalla lo dice.

### Las trece columnas que la vista no exponía

`mv_team_game_rates` no tenía `wins_before`, `losses_before`, `seconds_played`,
las ocho de origen de los puntos, ni `absent_minutes`/`absent_players`. No era
cosmético: `queries.py` bajaba a la tabla base para el récord, y la consulta de
`/stability` de la fase 20 tuvo que hacer lo mismo. La vista existe para evitar
justo eso.

Añadidas, y las dos consultas vueltas a apuntar a la vista. Comprobado:
13.204 filas y **0 discrepancias** contra la tabla base. `/stability` sigue dando
los mismos `k` (3,0 · 5,3 · 6,9 … 47,0 · 150,5).

De paso, el comentario de `maintenance.py` decía "en orden de dependencia: cada
una lee de la anterior". Es cierto para las tres primeras; `mv_team_game_rates`
lee de `team_game_stats`, una tabla base. Corregido.

### Contradicciones con el propio contrato

`TEMPORADAS = ['2025-26', …]` estaba escrito a mano en dos pantallas mientras el
docstring de `/catalog` decía literalmente que eso se desfasa. `TeamPage` **ya
pedía `/catalog`** y le ignoraba el campo `seasons`. Y `Layout` mostraba
"5 temporadas · 6.602 partidos" como texto fijo.

Las tres leen ahora del catálogo, que devuelve un bloque `counts` nuevo.

### Muerto fuera

Verificado con cero usos: `kaggle_username`, `kaggle_key` y
`backfill_window_days` en `config.py` (y sus líneas en `.env`); `polars`,
`pyarrow`, `duckdb` y `httpx` en `pyproject.toml` — **cero imports en todo el
repo**; `fmtRecord`; los dos `export { fmt }` sueltos; y `pbp.log`, con `*.log`
añadido a `.gitignore`.

**Corrección a la auditoría:** daba por muertos `api.headToHead` y
`/teams/{a}/vs/{b}`, y ya no lo están — se cablearon en la fase 18b.

Con eso, `oxlint` pasa de seis advertencias a **cero**. La última exigía mover
`COLORES_SERIE` fuera del fichero del gráfico, y tiene consecuencia real: un
módulo que exporta componentes *y* constantes rompe el fast refresh.

### Robustez

- **Ruta 404.** Antes, cualquier URL desconocida pintaba una página **en blanco**:
  sin error, sin navegación y sin forma de saber si la aplicación se había roto.
- **`response_model` en los ocho endpoints que no lo tenían.** Construían su
  `dict` a mano y los tipos de TypeScript se escribieron para casar, que es una
  divergencia esperando a ocurrir. **La validación cazó un error en cuanto se
  activó**: yo había puesto `detail` como obligatorio en los componentes de
  `/predict`, y ahí no existe. Exactamente para eso sirve.
- **Test de `temporada_actual`**, que era lógica sin verificar **y es la que
  decide qué temporada carga `daily`**. Si el corte de octubre se equivoca, la
  actualización diaria recarga la temporada equivocada durante semanas sin dar un
  error. 14 casos: el corte del 30 de septiembre al 1 de octubre, diciembre
  contra enero, el cambio de década (2029-30, no "2029-3"), el de siglo
  (2099-00), un bisiesto, y que 1.200 días consecutivos nunca retrocedan.

### La duplicación convertida en salvaguarda

`analysis/rates.py` (170 líneas) calcula per-36, TS%, eFG% y Game Score en
Python; las vistas los calculan otra vez en SQL; **y la API solo usa las de
SQL**. Nada garantizaba que coincidieran.

Ahora hay un test que las cruza — y **encontró algo en la primera pasada**. TS%
y eFG% fallaban por exactamente 0,0005, siempre. No era un error de fórmula:
**a nivel de partido esos valores no los calcula nadie nuestro**, vienen de
`player_game_advanced`, o sea de la NBA, con 3 decimales. Son dos preguntas
distintas y yo las había mezclado en un solo test con una sola tolerancia:

| | Qué compara | Desviación |
|---|---|---|
| Temporada | Python contra **SQL** | 5e-5 = redondeo de `numeric(6,4)` |
| Partido | Python contra **la NBA** | 5e-4 = redondeo de sus 3 decimales |

La segunda también vale la pena, pero es otra cosa: confirma que nuestra fórmula
es la misma que la de la liga. Separadas, las ocho comprobaciones pasan, y el
test exige que la peor diferencia sea **exactamente** el redondeo esperado — si
fuera menor, el dato no vendría de donde se cree.

El test se salta limpiamente sin base de datos (comprobado), para no romper la
propiedad de que los otros ~500 corren en dos segundos en cualquier máquina.

### El fallo que apareció al correr `daily` de verdad

La verificación pedía ejecutar `daily` entero y comprobar que es idempotente. No
lo fue, y el motivo es interesante.

`daily` corrió `enrich`, que marcó como **sede neutral** cuatro partidos de
2023-24 que no lo estaban: las dos semifinales de la Copa NBA en Las Vegas
(LAL-NOP y MIL-IND, 7 de diciembre), el de París (CLE-BKN) y el de México
(ORL-ATL). El corrector hizo bien su trabajo — el modelo excluye las sedes
neutrales a propósito, porque la localía es una de sus variables.

Pero **sus predicciones viejas se quedaron en la tabla**. `upsert` escribe y
actualiza; no borra lo que deja de producirse. Resultado: `game_predictions`
tenía 4.910 filas cuando la corrida había generado 4.906, y esas cuatro
sobrantes llevaban coeficientes de otra corrida. `/model/backtest` las habría
contado.

Arreglado borrando, tras cada pasada, lo que tenga un `fitted_at` anterior a
ella. Y con dos tests que lo vigilan: que ninguna predicción sea de un partido
que el modelo excluye, y que todas compartan corrida — si conviven dos
`fitted_at`, unas se calcularon con otros coeficientes.

**Las métricas cambian un pelo por esto, y el cambio es una corrección**: 65,76 %
sobre 4.906 partidos, en vez del 65,70 % sobre 4.910. No se movió el modelo; se
quitaron cuatro partidos que nunca debieron estar.

### Y el SQL fuera de `cli.py`

`build-ratings` eran 120 líneas con su consulta embebida, mientras todos los
demás comandos delegan en un módulo. Ahora vive en `ratings_job.py`, que además
es lo que permite que `daily` lo llame: un comando de Typer no se puede invocar
limpiamente desde otro. Reajustar tras el refactor da **exactamente** las mismas
métricas, que es la comprobación de que solo se movió de sitio.

---

## Fase 22 — Calidad de tiro: segundo resultado negativo, y esta vez con mecanismo

La última vía con mecanismo real para rescatar el motor de resultado esperado.
**No la rescata**, y ahora se sabe exactamente por qué.

### El criterio, escrito antes de mirar

Copiado del plan y sin tocar después: la media de los primeros k partidos debe
predecir el margen medio del resto de la temporada con menor RMSE que el margen
real. **Si a k=10 y k=20 no gana, se publica el negativo y se cierra.**

Estimador principal: el margen real quitando la suerte de tiro de los dos
equipos, donde "suerte" es lo anotado por encima de lo esperado **según dónde se
tiró**. Cualquier variante secundaria no cambia el veredicto.

### Un fallo de datos que había que encontrar primero

**75.849 triples —el 16 % de todos— venían con `shot_distance = 0`**, que es
imposible. No era corrupción: es sistemático, un 16 % en las cinco temporadas.
Sus coordenadas dan una distancia de 21,9 a 23,5 pies. Son los **triples de
esquina**, que la NBA reporta con distancia cero.

Construir sobre `shot_distance` habría etiquetado el tiro más eficiente del
baloncesto como un tiro a bocajarro. Se usan las coordenadas, validadas contra
la distancia declarada donde ésta no es cero: sobre 1.048.714 tiros, diferencia
media de 0,25 pies y **ni uno solo** que discrepe más de 1,5.

Con eso, el dato que justificaba la vía aparece limpio: la esquina entra al
**38,52 %** y el resto del arco al **35,05 %**, tres pies más lejos.

El motor cuadra exacto contra el box score: los puntos de campo reconstruidos
desde el play-by-play coinciden con `2·FGM + FG3M` en los **13.204** equipo-partido,
sin una excepción.

### El resultado

RMSE fuera de muestra, 150 equipos-temporada:

| k | Margen real | Calidad de tiro (los dos) | Solo el ataque | Solo lo concedido |
|---|---|---|---|---|
| 10 | **5,003** | 5,869 | 6,112 | 5,420 |
| 20 | **4,300** | 5,367 | 5,558 | 4,819 |
| 30 | **4,261** | 5,241 | 5,330 | 4,656 |
| 41 | **4,254** | 5,491 | 5,364 | 4,713 |

**Pierde en los cuatro cortes, entre un 17 % y un 25 %.** Peor que las cinco
formulaciones de la fase 13. No hay ambigüedad que interpretar.

### Por qué falla, que es lo que hace útil el negativo

La hipótesis tenía dos mitades. La primera se confirma; la segunda es falsa.

| | k | Clase |
|---|---|---|
| Calidad de tiro por intento — la **decisión** | **5,9** | Habilidad |
| Anotado por encima de lo esperado — el **acierto** | **14,2** | **Habilidad** |
| Margen real | 8,4 | Habilidad |

**El acierto condicionado a la localización NO es ruido: se estabiliza en 14
partidos.** El estimador estaba tirando a la basura algo que se repite, y por eso
empeora. Condicionar por dónde se tira no convierte el resto en azar.

Y entre temporadas, que es la prueba que no admite "racha caliente":

| | ρ |
|---|---|
| Anotar por encima de lo esperado | **+0,584 ± 0,061** |
| Calidad de tiro (la decisión) | +0,557 ± 0,063 |
| *(referencia: el neto del equipo, fase 18)* | *+0,542* |

**El "acierto" persiste entre temporadas MÁS que la propia elección de tiro, y
más que el neto del equipo.** Sobrevive al verano, a los traspasos y al draft.
Llamarlo suerte era sencillamente falso — es talento de tiro, que es de las
cosas más reales que hay en el baloncesto.

### Y además ya estaba contado

Controlando por la diferencia de rating ajustado por rival, la habilidad de tiro
**no añade nada**: ΔR² de 0,003 puntos, coeficiente −0,022 con p=0,619. Su
correlación con el rating es de **+0,572**. Los ratings ya la llevan dentro,
porque un equipo que mete más tiros anota más y eso es exactamente lo que el
rating mide.

Así que no solo no mejora el estimador: no había nada que añadir.

### Qué queda

La línea se cierra, como decía el criterio. Lo que se queda escrito:

1. **El triple de esquina viene con `shot_distance = 0`.** Es una trampa que
   cualquiera volvería a pisar.
2. **El acierto de tiro es habilidad** (k=14,2, ρ=+0,584), y no debe tratarse
   como ruido en ningún motor futuro. Es la tercera vez que este proyecto
   tropieza con lo mismo: en la fase 13 con el acierto de 2 y el de libres, y
   aquí con el acierto condicionado a la localización.
3. **La calidad de tiro sí es una característica estable de equipo** (k=5,9,
   ρ=+0,557). No sirve para estimar fuerza mejor que el margen, pero describe
   bien cómo genera sus tiros un equipo. Queda medido, sin endpoint, con el
   motivo escrito — el mismo precedente que la curva de edad.

Dos resultados negativos seguidos sobre la misma pregunta, los dos con su prueba
fijada antes y publicados enteros. El motor de resultado esperado se queda donde
estaba en la fase 13: **la atribución es exacta y se publica; el veredicto sobre
el mérito no**.

---

## Fase 23 — La curva de edad, por fin sin sesgo de supervivencia

La pregunta que el proyecto llevaba desde la fase 4 llamando "la más valiosa", y
la única funcionalidad con endpoint **deliberadamente no expuesto** porque el
método para responderla no estaba.

### El sesgo, y por qué es tan grande

La curva transversal ajusta todos los jugadores y todas las edades a la vez. El
problema es que a los 36 años **solo quedan los que envejecieron bien**: quien
declinó de verdad no aparece promediando poco, aparece fuera de la liga. La
muestra se selecciona sola y el declive se le escapa.

Los números del proyecto lo enseñaban: pico a los 28,9 años y solo un 2 % de
caída a los 34. Ningún deportista real se comporta así.

### El método delta

Comparar a cada jugador **consigo mismo** entre temporadas consecutivas. Al ser
intra-jugador, quién entra o sale de la liga deja de importar.

| Edad | Transversal | Delta |
|---|---|---|
| 22 | 96,0 % | 92,1 % |
| 25 | 98,7 % | 100 % |
| 28 | 99,9 % | 99,7 % |
| 31 | 99,6 % | 97,4 % |
| **34** | **97,8 %** | **89,3 %** |

Los dos se devuelven juntos en `/age-curve` y se dibujan juntos en pantalla, a
propósito: **el argumento es la diferencia**, y enseñar solo la corregida
obligaría a creérsela.

### La prueba: un mundo sintético donde la verdad se conoce

Se inventa una curva, se generan 400 carreras, y se les aplica la misma regla
que aplica la liga — al que baja de un umbral se le deja de fichar y no vuelve.
Entonces se pregunta qué método recupera la curva verdadera:

| Edad | Verdad | Transversal | Delta |
|---|---|---|---|
| 30 | 89,0 % | 93,1 % | 90,1 % |
| 32 | 75,2 % | 83,7 % | 77,3 % |
| **34** | **56,0 %** | **70,3 %** | **61,7 %** |
| 36 | 31,2 % | 53,1 % | 42,4 % |

**El delta corrige más de la mitad del error.** Y se queda corto, que es
exactamente lo que promete: hay un test que **exige** que no sobrepase el
declive real, porque un jugador solo aporta el paso de t a t+1 si jugó las dos
temporadas, y quien se cae a los 34 aporta su último paso pero no el siguiente.
Si algún día ese test empezara a fallar por acertar, habría que revisar el aviso.

### El hallazgo que el sesgo escondía

Por tramos, contra uno mismo, y sobre cuatro estadísticas independientes:

| Tramo | Puntos/36 | Game Score | TS% | Minutos |
|---|---|---|---|---|
| 19-22 | +1,268 * | +1,477 * | +0,010 * | +1,425 * |
| 23-25 | +0,256 | +0,356 * | +0,003 | +0,149 |
| 26-28 | −0,034 | −0,042 | +0,001 | −0,303 |
| 29-31 | −0,103 | −0,477 * | +0,002 | −1,231 * |
| **32+** | **−0,615 \*** | **−0,987 \*** | −0,003 | **−2,008 \*** |

*(\* = se distingue de cero al 95 %)*

**La eficiencia de tiro no envejece.** El TS% y el eFG% no muestran caída
distinguible ni siquiera pasados los 32; las asistencias tampoco. Lo que cae son
los puntos, los rebotes, el Game Score y sobre todo **los minutos: −2,0 por
temporada**. No se pierde puntería ni criterio: se pierde el rol.

Los pasos de un año, por separado, casi nunca alcanzan significación — con cinco
temporadas cada transición tiene entre 20 y 90 jugadores. Los tramos son la
lectura sobre la que se puede afirmar algo, y así se enseña.

### Dónde vive

En `/tendencias`, debajo de la lista de jugadores al alza y en declive, que es
donde tiene sentido: sin la curva, "este jugador cae" no se distingue de "este
jugador tiene 34 años y le pasa lo que a todos". Que era la pregunta.

---

## Fase 24 — Titularidad y DNP: 31.545 filas nuevas sin romper nada

La última pieza que necesitaba red. **6.599 peticiones, 0 fallos**, unos 78
minutos — la estimación de la auditoría (~1,3 h) era la buena; la mía de "3
horas" salió de los primeros minutos, que van lentos por el arranque.

### Dos trampas, encontradas antes de pagar la descarga

**La titularidad no es un campo.** No existe `starter`: lo que hay es
`position`, rellena solo para los cinco titulares y vacía para el resto.
Comprobado sobre los 6.602 partidos: **cero** con un número de titulares
distinto de 10.

**El endpoint añade filas.** Trae a quien no jugó, con el motivo. Los `NWT`
("not with team") permiten separar tres niveles que antes eran uno: no está
disponible, está disponible y no juega, y ni siquiera viajó.

| Motivo | n |
|---|---|
| DNP - Coach's Decision | 26.166 |
| DND - Injury/Illness | 4.480 |
| NWT - Not With Team | ~190 |
| DND - Rest | ~130 |

### Lo que esas filas habrían roto, y no rompieron

Cinco sitios, todos en silencio. Se midió el daño ejecutando la lógica vieja
**con los datos ya dentro**:

| | Correcto | Sin el arreglo |
|---|---|---|
| `games_played` inflado | 22 | **28.619** |
| `fg3a_per_game` de Kyle Lowry | 1,79 | **0,30** |
| Índice de ausencias, media | 72,46 min | **43,39** |
| Partidos con 100+ min fuera | 3.126 | **1.181** |

Lo del índice es lo más instructivo: buscaba **filas inexistentes**, así que un
lesionado con fila de lesionado habría dejado de contar como ausente justo por
tenerla. Y **habría seguido pareciendo correcto** — el gradiente roto daba
57,3 % → 31,0 %, monótono y hasta más pronunciado. Nada habría avisado.

Un detalle que sí protegía solo: los promedios por partido usan `AVG()`, que
ignora los nulos, así que `pts_per_game` nunca estuvo en peligro. Los que
dividen explícitamente por `COUNT(*)` sí.

**La invariante que lo cierra:** tras cargar 31.545 filas y rehacer las vistas,
la capa de tasas tiene **140.932 filas, exactamente las mismas que antes**, y el
índice de ausencias no se movió ni un decimal (72,46 min · 3.126 partidos).

### Un hallazgo de la fuente

Una fila —Thomas Bryant, 23/02/2024— viene **sin motivo de DNP, con 0 segundos y
sin estadísticas**: ni jugó ni consta por qué. No es lo mismo que las 22 filas de
0 segundos que sí traen ceros reales (ésas son apariciones: entró y no le dio
tiempo a nada). La capa de tasas exige ahora línea de box score, que es lo que
hace cuadrar la invariante al dígito.

### Lo que desbloquea

- **Split titular/suplente**, dimensión nueva de los splits. Llevaba previsto en
  `mv_player_game_rates` desde la fase 4 esperando solo a que la columna tuviera
  datos. Con su aviso: salir de inicio no es una condición del jugador sino una
  decisión del entrenador, que suele seguir al rendimiento y a las lesiones de
  otros.
- **El porqué de cada ausencia** en la ficha de partido. Y una complementariedad
  que no era obvia: el motivo explica las ausencias **cortas**, mientras el
  índice inferido caza las **largas** — a Markkanen o Morant, fuera meses, la
  fuente ni los lista en el partido.

---

## Fase 25 — Dónde está el techo, y qué es lo único que lo mueve

De una pregunta —"¿se puede predecir la 2025-26 congelando todo en junio?"— salieron cinco
mediciones que contestan algo más grande. Ninguna costó una petición a la NBA.

### El modelo está en su techo, y se puede demostrar

Si el margen esperado de cada partido fuera **exacto**, con σ=13,81 el acierto máximo alcanzable
sería del **64,28 %**. El modelo acierta el **65,76 %** — está en el límite, y por encima de su
propio techo calculado porque su calibración es un pelo conservadora (pendiente 1,07), lo que hace
que ese cálculo se quede corto.

Lo que limita el acierto no es el modelo: es que un partido de la NBA tiene 13,8 puntos de ruido
frente a un margen esperado medio de 5,3.

**Y sabe cuáles sabe**, que es el verdadero producto:

| Lo que dice el modelo | Partidos | Acierto real |
|---|---|---|
| 50-55 % (casi moneda) | 1.044 (21 %) | **52,4 %** |
| 55-65 % | 1.675 (34 %) | 60,1 % |
| 65-75 % | 1.280 (26 %) | 72,4 % |
| 75 %+ | 907 (18 %) | **82,2 %** |

Monótono en los cuatro tramos. Cuando dice que no lo sabe, **tiene razón en no saberlo**.

### Congelar en junio no funciona, para ningún producto

Se predijo la 2025-26 entera sin un solo dato de la 2025-26. Las constantes se re-derivaron
excluyéndola, porque usar las publicadas habría sido fuga: la persistencia sobre 3 transiciones da
**0,531 / 0,597**, no los 0,450 / 0,554 medidos con las cuatro.

| | Acierto |
|---|---|
| Congelado en junio | 59,84 % |
| Mejor récord de 2024-25 | 59,43 % |
| Siempre gana el local | 55,43 % |

**+0,41 puntos sobre la línea base tonta**, y la calibración se rompe: pendiente 0,849, o sea
exceso de confianza — usa ratings de junio como si fueran de hoy. Congelar cuesta **seis puntos**
frente al walk-forward normal.

Como proyección de temporada tampoco: error medio de **9,68 victorias** contra las 10,30 de "lo
mismo que el año pasado", con fallos de hasta **±25 victorias**. Un equipo proyectado con 36 ganó 61.

La causa está medida desde la fase 18: un equipo conserva **ρ≈0,5** de su identidad tras un verano,
y lo que decide el resto —traspasos, draft, desarrollo, lesiones— no existe en junio.

### Una cifra que di mal, y su corrección

En la conversación afirmé que los "+3 puntos" de las alineaciones se sumarían al 65,76 %. **Era
falso.** Aquellos +3 pp eran del escenario congelado, donde no hay ratings actualizados que
absorban la información. Medido sobre el sistema real:

| | Acierto | Brier | log-loss |
|---|---|---|---|
| Hoy | 65,76 % | 0,2133 | 0,6147 |
| + todas las ausencias | 66,84 % | 0,2104 | 0,6083 |
| **+ solo lo conocible antes del partido** | **67,24 %** | **0,2090** | **0,6051** |

**+1,49 pp con p=0,0003**, no +3. Los ratings actualizados ya absorben buena parte de la
información: un equipo que juega sin sus estrellas acumula peores resultados y su rating baja solo.
Las ausencias solo añaden lo que el rating aún no ha visto — la baja de **esta** noche.

### El hallazgo bueno: el parte de lesiones bate a la alineación real

Reparto de los minutos ausentes según si se saben antes del salto inicial:

| Motivo | Minutos | % | ¿Se sabe antes? |
|---|---|---|---|
| Ni figura en el acta (baja larga) | 670.885 | 70,1 % | Sí |
| Decisión técnica | 191.556 | **20,0 %** | **No** |
| Lesión o enfermedad | 89.513 | 9,4 % | Sí — parte oficial |
| Descanso / no viajó | 4.813 | 0,5 % | Sí |

Y aquí está lo que no se esperaba: **usar solo el 80 % conocible da MÁS (+1,49 pp) que usarlo todo
(+1,08 pp)**.

El "DNP - Decisión técnica" no es una ausencia útil. Es un jugador sano al que el entrenador no
usó, muchas veces con el partido ya decidido o porque es el duodécimo hombre. **Añade ruido, no
señal**, y el parte de lesiones lo filtra por construcción.

Consecuencia práctica: **no hace falta la alineación anunciada**. El parte de lesiones y la lista de
inactivos, que salen ~1 h antes, son suficientes y además mejores.

**Con su salvedad, que es importante:** esta medición reconstruye el parte desde el box score, o sea
simula un parte **perfecto**. Uno real tiene "duda" y "probable" y algunos de ésos acaban jugando,
así que el número real quedaría algo por debajo de 67,24 %. Y no hay endpoint histórico —la NBA lo
publica en PDF—, así que solo podría capturarse hacia adelante.

### El montaje, para que se pueda repetir

Dos detalles sin los cuales estas cifras estarían infladas:

1. **Constantes re-derivadas excluyendo la temporada objetivo.** Persistencia, λ y el coeficiente de
   ausencias se midieron con las cinco temporadas; usarlos para predecir una de ellas es fuga.
2. **Índice de ausencias sin fuga.** Los "minutos habituales" se calculan con una media móvil hasta
   el partido **anterior**, no con la temporada entera. El coeficiente honesto sale entre **+0,0287
   y +0,0432** según el año, no el +0,0373 publicado.

El `PUNTOS_POR_MINUTO = 0,0373` de `absences.py` **no se toca**: es el correcto para explicar un
partido ya jugado, que es para lo que se usa. Un sistema prospectivo necesitaría el otro, y todavía
no hay dónde usarlo.

---

## Fase 26 — La titularidad se borraba sola cada noche

Un subagente revisor de la capa PostgreSQL (`.claude/agents/database-reviewer.md`,
solo lectura: sin `Edit`, sin `Write`, sin `Bash`) encontró un fallo que la suite
de 513 tests no podía ver, porque no es un error de cálculo sino de **propiedad
de las columnas**.

`upsert()` actualizaba todas las columnas que no fueran clave:

```python
updatable = [c.name for c in model.__table__.columns if c.name not in keys]
set_={name: stmt.excluded[name] for name in updatable}
```

`EXCLUDED` vale NULL en toda columna que no viaje en el `INSERT`. Y `daily`
arranca recargando la temporada en curso entera. Así que cada pasada nocturna
ponía a NULL lo que escribe otra ingesta: `started` y `dnp_reason`
(starters.py), `attendance` y `arena_name` (summaries.py), `game_label` y
`game_sublabel` (enrich.py), la ficha de franquicia y la conferencia (teams.py),
y las cuatro derivadas de derive.sql.

**Lo que lo volvía permanente en el caso de la titularidad:** `ingest_starters()`
no tenía ningún llamador. Cero referencias fuera de su propio módulo en todo
`src/` y `tests/` — ni comando en `cli.py`, ni test. Las 31.545 filas de la fase
24 se cargaron a mano y nada las reponía.

Las dos consecuencias, y por qué no se vieron:

- `mv_player_season.games_started` = `COUNT(*) FILTER (WHERE started)` daba **0**
  para toda la temporada en curso.
- El split titular/suplente metía a los cinco titulares en `'suplente'`, porque
  `CASE WHEN NULL` cae al `ELSE`.

Ninguna de las dos es un error visible. Son **respuestas plausibles**: un 0 y una
comparación que se puede leer sin sospechar. Es exactamente el modo de fallo
contra el que existe la capa de honestidad estadística de este proyecto, colado
por debajo, en la ingesta.

Lo curioso: el docstring de `starters.py` ya describía el mecanismo —«el upsert
genérico pone a NULL toda columna que no venga en la fila»— y lo esquivaba con un
`UPDATE` dirigido. Se vio el problema en local y no se vio que `bulk.py` hacía
justo eso, en sentido contrario, cada noche.

**El arreglo**, en dos mitades que hacen falta las dos:

1. `upsert()` actualiza solo las columnas presentes en las filas (unión de todas,
   no las de la primera). Con `on_conflict_do_nothing()` cuando no queda nada
   fuera de la clave, porque un `SET` vacío es un error de sintaxis en Postgres.
2. Comando `ingest-starters` y su llamada en `daily`. Sin esto el arreglo no
   basta: `ingest_seasons` inserta a los que jugaron **sin** `started`, así que
   las filas nuevas nacen sin informar aunque las viejas ya no se borren.

Y se quitaron los `None` explícitos de los cuatro constructores. El comentario
que los justificaba —«se pasan explícitas a None porque el upsert pone a NULL
toda columna ausente»— documentaba el fallo como si fuera el diseño.

8 tests nuevos, de los que **7 fallan contra el código anterior** (el octavo es
un guarda de la clave, que ya era correcto). Suite: 521 pasan.

### Lo que queda abierto de esa revisión

- **Reparar los datos ya en blanco.** El arreglo corta la causa, no rehace lo
  perdido. Pide un `ingest-summaries --all` (~1,5 h) y un `ingest-starters --all`
  (~1,3 h) una vez. **No** se cambió el criterio de `only_missing` a
  `arena_name IS NULL`: hay partidos sin pabellón en la fuente, y volverían a
  pedirse cada noche para siempre.
- **`ot_periods`** lo sigue pisando la heurística `round((MIN-48)/5)` de
  `bulk.py` sobre el valor exacto de `summaries.py`. Viaja en el payload, así que
  el arreglo del upsert no lo cubre.
- Nueve hallazgos más, de media y baja: las cuatro transacciones separadas de
  `refresh_views()` (un INNER JOIN pierde el partido de anoche), la cabecera de
  `summaries` fuera de la transacción de los periodos, los `CHECK` de rango que
  faltan en las columnas de fracción (`numeric(6,4)` solo caza escalas ≥ 100),
  texto sin recortar en columnas de ancho fijo, cuatro índices sobrantes, y
  `/teams/{a}/vs/{b}` promediando temporada regular y playoffs.

Lo que salió limpio, comprobado uno a uno: los 17 `ON CONFLICT` tienen respaldo
exacto en la PK de su tabla, y las cuatro vistas materializadas tienen su
`CREATE UNIQUE INDEX`, así que `REFRESH CONCURRENTLY` funciona en todas.

## 🔵 Estado y siguientes pasos

El sistema está **completo y funcionando de punta a punta**. Levantarlo:

```bash
uv run uvicorn nbastats.api.main:app --reload    # API en :8000
cd web && npm run dev                            # interfaz en :5173
```

La auditoría de la fase 17 revisó el proyecto entero. **Los cimientos no se
tocan**: la separación entre `analysis/` puro y `api/` con SQL se ha mantenido
sin una grieta en 11 módulos, el walk-forward no tiene fuga, y la disciplina de
publicar los resultados negativos (la curva de edad, el motor de resultado
esperado) es un activo. Lo que hay no está mal construido; lo que sobra es
**distancia entre lo construido y lo cableado**.

Orden acordado para lo siguiente.

1. **Reparar los datos que el upsert dejó en blanco** (fase 26): un
   `ingest-summaries --all` y un `ingest-starters --all`, una vez.
2. **Play-by-play** (~6.600 peticiones) — lo único sin atajo por endpoint
   masivo. Desbloquea clutch, desglose por cuartos y zonas de tiro.
3. **Pantalla de head-to-head** — el endpoint `/teams/{a}/vs/{b}` existe desde
   la fase 20 y no tiene interfaz. Arreglar de paso que promedia temporada
   regular y playoffs en una sola cifra.


Descartado a propósito: quintetos como funcionalidad destacada (los 319.323
eventos de sustitución tienen `sub_type` vacío y el jugador que entra solo existe
en el texto; y el décimo quinteto juega ~40 minutos en toda la temporada), más
variables persiguiendo p<0,05, y cualquier cosa con `scikit-learn` — con 6.150
filas y σ≈13 puntos de ruido irreducible, la señal cabe en cinco coeficientes.

Lo que se aprendió tres veces seguidas y conviene tener presente: **antes de
pagar una pasada por partido, comprobar si el endpoint masivo admite el filtro.**
Los cuartos costaron 93 peticiones en vez de 26.400, y de dónde salen los puntos
costó 15 en vez de 6.602. Solo el play-by-play no tenía atajo.
