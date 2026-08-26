# Qué se puede preguntar y qué no

Documento vivo. Se actualiza cada vez que cambia el esquema o se carga una
fuente nueva.

Sirve para responder, antes de escribir la consulta, a: *"¿esta pregunta se
puede contestar con lo que tenemos, y el número va a significar algo?"*

Hay **dos tipos de límite distintos** y conviene no confundirlos:

| | Límite A — **estructural** | Límite B — **estadístico** |
|---|---|---|
| Qué pasa | El dato no está en la base | El dato está, la consulta corre |
| La consulta… | no se puede ni escribir | devuelve un número |
| El problema | falta información | el número no distingue señal de ruido |
| Se arregla… | cargando otra fuente | juntando más partidos, o no se arregla |

El sistema **no bloquea** las preguntas de tipo B. Las responde acompañadas de
`n`, intervalo de confianza y semáforo de confiabilidad
(`analysis/reliability.py`), para que se vea de un vistazo cuánto peso aguanta
la conclusión.

---

## 1. Lo que sí se puede responder hoy

Con `player_game_stats` + `player_game_advanced` + `team_game_stats` + `games`:

**Por partido, cualquier estadística de box score**
puntos, rebotes (of/def/total), asistencias, robos, tapones, pérdidas, faltas,
tiros de campo / triples / libres (anotados e intentados), +/-, minutos, y las
avanzadas: TS%, eFG%, USG%, AST%, REB%, TOV%, rating ofensivo/defensivo, ritmo,
PIE.

(La **titularidad** no está: ver §2.)

**Desglose por cuarto**
puntos, rebotes, asistencias, robos, tapones, pérdidas, +/- y minutos de cada
jugador **en cada periodo** (`player_period_stats`, 481.863 filas). Las
prórrogas van numeradas desde 1: el periodo 5 se lee como "1ª prórroga".

Es, de todo lo que hay por debajo del partido, **el dato con mejor muestra**: un
titular acumula ~70 cuartos cuartos por temporada y ~350 en cinco, muy por
encima del umbral de fiabilidad alta (n≥40). Está disponible como una dimensión
más de los splits, así que llega con encogimiento bayesiano, intervalo y
corrección por comparaciones múltiples como cualquier otra.

> **Los puntos de un cuarto no se leen sin sus minutos.** El cuarto cuarto
> mezcla dos cosas opuestas: cerrar partidos igualados y estar sentado en las
> palizas. Jokić anota 8,1 en el primer cuarto y 6,0 en el cuarto, pero es que
> juega 10,6 y 7,2 minutos respectivamente — y aparece en 357 primeros cuartos
> frente a 295 cuartos cuartos. El propio `n` delata el sesgo. Por eso los
> minutos son una estadística seleccionable de esta dimensión.

**No hay tasas por cuarto, y es deliberado.** `player_period_stats` guarda
totales y segundos, nada más. Extrapolar a 36 minutos desde los 4 que alguien
jugó en un tercer cuarto produce los mismos disparates que el `pace` de jugador.
Pedir `pts_per_36` con dimensión "cuarto" devuelve 422, no una columna de nulos.

**Contexto del partido**
marcador por cuarto de cada equipo, asistencia, pabellón, árbitros y periodos de
prórroga reales. Faltan en 3 partidos de 6.602 (`0022500259/260/261`, 19-11-2025):
la NBA devuelve su resumen con todos los campos a `null`. Es un hueco de la
fuente y la ficha lo dice en pantalla en vez de pintar ceros.

**Récord con el que cada equipo llegaba a un partido**
victorias y derrotas ANTES de ese partido, sin contarlo
(`team_game_stats.wins_before` / `losses_before`, derivadas en `derive.sql`).
Se cuentan dentro del mismo tipo de temporada: en un partido de playoffs es el
recorrido en esos playoffs, no el 58-24 de la fase regular. Validado: el récord
tras el último partido de cada equipo coincide con `team_standings` en los 30
equipos.

**Agregado por cualquier dimensión que viva en `games` o `team_game_stats`**
temporada, tipo de temporada (regular / play-in / playoffs), mes, día de la
semana, local/visitante, rival, días de descanso, back-to-back, victoria/derrota,
edad del jugador ese día, hora de inicio del partido, equipo (resuelve traspasos
a mitad de temporada).

> **Al filtrar por local/visitante, excluye `is_neutral_site`.** Unos 5 partidos
> por temporada se juegan en París, Ciudad de México o Las Vegas. La NBA designa
> un local nominal por contabilidad, pero ahí no hay ventaja de campo: ni
> público propio, ni rutina, ni ausencia de viaje. Contarlos como "local" mete
> ruido en las dos direcciones a la vez.

**Tendencias a lo largo del tiempo**
medias móviles, tasas per-36 y per-100 posesiones, pendiente con intervalo de
confianza, test de Mann-Kendall, detección de puntos de cambio, z-scores
normalizados contra la liga de esa misma temporada.

**Comparaciones entre jugadores**
en cualquiera de las métricas anteriores, normalizadas por ritmo y por año.

**Fichas de jugador y equipo**
dorsal, estatus, experiencia, equipo actual, draft, procedencia; foto y logo
enlazados al CDN de la NBA. Por equipo: estadio, capacidad, entrenador,
director general, plantilla de cada temporada y calendario completo.

**Tipo de cada partido**
temporada regular, NBA Cup (con su ronda), play-in, playoffs (con ronda y
número de partido) y partidos internacionales. Se deriva de tres campos, no de
una columna: **un partido de la NBA Cup es un partido de temporada regular** —
son 66 de los 1.230 de cada año, y solo la final queda fuera del cómputo.

**Análisis de equipo**
las mismas tendencias y splits que los jugadores, normalizados per-100
posesiones en vez de per-36 minutos: un equipo siempre juega 48 minutos, así
que lo que distingue no son los minutos sino cuántas posesiones caben dentro.

**Clasificación y enfrentamientos directos**
posiciones oficiales con los desempates de la NBA ya aplicados, récords
desglosados y historial entre dos equipos cualesquiera.

**Ficha completa de un partido**
box score de los dos equipos y de todos los jugadores, tradicional y avanzado:
minutos al segundo, tiros de campo, triples y libres con aciertos e intentos,
rebotes ofensivos y defensivos, +/-, TS%, eFG%, USG%, AST%, REB%, ratings, PIE
y Game Score. Más el contexto del partido: días de descanso de cada equipo,
prórrogas, ritmo y posesiones.

**Historial de un equipo con filtros**
por localía, resultado, tipo de partido, rival y descanso, con el récord y el
diferencial del subconjunto recalculados. Cada partido enlaza a su ficha.

---

## 2. Límite A — estructural: lo que NO se puede preguntar

Todo lo de esta lista necesita **play-by-play o datos de tiro**, que hoy no
están cargados.

> **Esta sección se ha vaciado casi entera.** El rendimiento por cuarto salió de
> aquí con `PlayerGameLogs(Period=N)` (93 peticiones), y el play-by-play —ya
> cargado, 3.251.908 eventos en los 6.602 partidos— se llevó por delante el
> clutch, las rachas, los quintetos, quién asiste a quién y las zonas de tiro.
> Ver §7.
>
> Cuidado con una distinción que esto NO borra: que el dato exista no significa
> que la pregunta tenga respuesta sólida. El clutch, por ejemplo, pasa del
> límite A al **límite B**: ahora se puede calcular, y sigue sin haber muestra
> para afirmar casi nada con él. Ver §3.

| Pregunta | Por qué no |
|---|---|
| "¿Cuánto anota en el clutch (últimos 5 min, ≤5 de diferencia)?" | El box score no tiene marca de tiempo. Haría falta play-by-play. |
| "¿Cómo rinde en el cuarto cuarto?" | El box score de jugador no viene desglosado por periodo. |
| "¿Desde qué zonas de la cancha tira mejor?" | Requiere coordenadas de tiro (`shot_chart_detail`). |
| "¿Qué quinteto funciona mejor?" / on-off | Requiere las sustituciones del play-by-play. |
| "¿A quién le da más asistencias?" | El box score cuenta asistencias, no quién las recibe. |
| "¿A quién defendió?" | Requiere datos de seguimiento (tracking), que ni siquiera están en el play-by-play. |
| "¿Anotó 10 puntos seguidos?" | Rachas intra-partido: play-by-play. |
| "¿Cómo le fue tras un tiempo muerto?" | Play-by-play. |
| "¿Rinde mejor como titular que saliendo del banquillo?" | `PlayerGameLogs` no marca quién fue titular. Requeriría una petición por partido (~6.600) en vez de una por temporada. |
| "¿Cuántos partidos se perdió por lesión?" | Solo aparecen los jugadores que jugaron: no hay filas de DNP ni motivo. Misma fuente y mismo coste que la anterior. Y ojo: ni siquiera con ella se distingue lesión de descanso programado o sanción. |
| "¿Fue un tiro abierto o contestado?" | El play-by-play da dónde se tiró, no quién estaba cerca. Requiere tracking. |
| "¿Por qué eligió ese tiro?" | Ninguna fuente lo tiene. |
| "¿Qué puesto ocupa en FG% de la liga?" | Se responde, pero con un umbral distinto al oficial: la NBA cualifica los porcentajes por mínimo de intentos (300 tiros anotados) y aquí se usa el de partidos. Los puestos de puntos, rebotes y asistencias sí coinciden exactamente con las fuentes públicas. |

Y un caso aparte, que no es de falta de datos sino de falta de señal:

| Límite | Detalle |
|---|---|
| Sedes neutrales de **2022-23** | La API expone `isNeutral` y `gameLabel` desde 2023-24, pero no los retropobló. Se comprobaron `MATCHUP`, `isNeutral`, `gameLabel`, `gameSubtype` y `BoxScoreSummaryV2` sin encontrar ninguna marca. Quedan 2 partidos (de 6.150) clasificados como local cuando se jugaron en París y Ciudad de México. Impacto: 0,03%. |

**Todo esto es ampliable, con coste conocido** — ver §7.

---

## 3. Límite B — estadístico: lo que se puede preguntar pero hay que leer con cuidado

Aquí la consulta corre y devuelve un número. La pregunta es cuánta confianza
merece.

### Cuántos partidos tiene realmente cada split

Referencia para un titular sano (~70 partidos por temporada, ~350 en cinco):

| Split | n en 1 temporada | n en 5 temporadas | Confiabilidad a 5 temporadas |
|---|---|---|---|
| Local / visitante | ~35 | ~175 | **Alta** |
| Mes concreto | ~12 | ~60 | **Alta** |
| Día de la semana | ~10-14 | ~50-70 | **Alta** |
| Back-to-back | ~12 | ~60 | **Alta** |
| Rival concreto | ~3 | ~15 | **Media** |
| Día × local/visitante | ~6 | ~30 | **Media** |
| Rival concreto × local | ~1,5 | ~8 | **Baja** |
| Día × rival | ~0,5 | ~2 | **Insuficiente** |

**Regla práctica: cada filtro que añades parte la muestra por la mitad
(o peor).** Dos condiciones combinadas suelen bastar para dejar la pregunta sin
respuesta útil.

### El caso concreto de "puntos en sábado"

Este es el ejemplo que originó el módulo, y la respuesta tiene matiz:

- **Estructuralmente sí se puede.** Guardamos `game_date_local`, el día sale con
  un `EXTRACT(DOW ...)`. No hay ningún impedimento.
- **En una sola temporada, no vale.** n≈12, desviación típica ≈6 puntos, error
  estándar ≈1,7. Una diferencia de 3 puntos frente a su promedio es
  indistinguible de cero.
- **En cinco temporadas, sí empieza a valer** (n≈60)… pero introduce otro
  problema: estás mezclando al jugador de 25 años con el de 30. Si además te
  interesa su curva de declive, ese promedio agregado tapa justo lo que buscas.
  **No hay forma de tener las dos cosas a la vez**; hay que elegir qué pregunta
  se está haciendo.
- **Ojo con las comparaciones múltiples.** 7 días × ~500 jugadores × ~10
  estadísticas ≈ 35.000 comparaciones. Con α=0,05 saldrían ~1.750 "hallazgos"
  puramente aleatorios. Por eso las vistas que escanean muchos jugadores aplican
  corrección de Benjamini-Hochberg y reportan `q`, no `p`.
- **Y ojo con los confusores.** Un aparente efecto de día suele ser en realidad
  efecto de descanso o de calidad de rival: los sábados hay más partidos
  televisados y más back-to-backs. El endpoint de splits controla por descanso,
  rival y localía mediante regresión.

### Las curvas de edad están sesgadas (y no poco)

`analysis/trends.fit_age_curve()` ajusta una curva transversal — todos los
jugadores, todas las edades, a la vez — y eso **subestima el declive por edad**
de forma severa. El motivo es sesgo de supervivencia: en la muestra solo entran
jugadores lo bastante buenos como para seguir jugando. Quien declina de verdad
no aparece con 36 años promediando poco; aparece **fuera de la NBA**, y
desaparece del cálculo.

Los números de este proyecto lo enseñan. Ajustada sobre 1.561 temporadas de
jugadores con 30+ partidos y 15+ minutos de media:

```
pico ajustado: 29,0 años
  21 años ->  94,4% del pico        33 años ->  98,6%
  24 años ->  97,8%                 36 años ->  95,7%
  27 años ->  99,7%                 39 años ->  91,2%
```

Un jugador de 39 años al 91% de su pico no describe a ningún deportista real:
describe a los pocos que sobrevivieron hasta los 39. La corrección estándar es
el **método delta** (comparar a cada jugador consigo mismo entre temporadas
consecutivas, lo que al ser intra-jugador no depende de quién entra o sale de
la liga). **No está implementado.** Hasta que lo esté, la curva sirve para
explorar la forma, no para afirmar cuánto declive es "normal" a una edad dada
— y por eso ningún endpoint la expone todavía.

### Los splits de equipo necesitan varias temporadas

Un equipo juega 41 partidos en casa por temporada. Con esa muestra **ni siquiera
la ventaja de campo** —un efecto real, conocido y medido— alcanza significación.
Comprobado con OKC y su rating neto:

```
Solo 2025-26 (n≈41):   local 11,50   visitante 10,79   q=0,84  -> ruido
Las 5 temporadas (n≈205): local  7,52  visitante  1,90  q=0,0007 -> REAL
```

Y el contraste de cordura sobre los 30 equipos y las 5 temporadas: **+1,93 en
casa contra −1,93 fuera**, que es la ventaja de campo que documenta la
literatura. El sistema no dice "sin patrón" por defecto — se niega a afirmarlo
cuando no hay potencia, y lo detecta cuando la hay.

Por eso el análisis de equipo abarca las 5 temporadas por defecto, con un
selector para acotarlo. La contrapartida es la de siempre: juntar cinco
temporadas mezcla plantillas distintas, así que "¿cómo juega este equipo?" y
"¿cómo juega esta franquicia?" son preguntas distintas y el selector obliga a
elegir cuál se está haciendo.

### Otras preguntas frágiles por el mismo motivo

- "¿Cómo rinde contra [un rival concreto]?" — n≈15 en cinco temporadas, y además
  la plantilla de ese rival cambió por completo en ese periodo.
- "¿Rinde peor en enero?" — n≈60, aceptable, pero enero concentra
  back-to-backs: controla por descanso antes de concluir nada.
- "¿Juega mejor en derrotas?" — sesgo de selección severo. El resultado del
  partido es en parte *consecuencia* de su rendimiento, no una condición previa.
- "¿Rinde distinto tras una derrota dura?" — la definición de "dura" es
  arbitraria y cada variante que pruebes es otra comparación más.

---

## 4. Referencia rápida

| Pregunta | Veredicto |
|---|---|
| Promedio de rebotes por partido, temporada 2024-25 | ✅ Directo |
| Media móvil de 25 partidos de su TS% | ✅ Directo |
| ¿Está en declive respecto a su curva de edad? | ✅ Directo |
| Puntos per-36 en local vs. visitante | ✅ Directo |
| ¿Cuántos puntos anota en el cuarto cuarto? | ✅ Directo — n≈70/temporada, ~350 en cinco |
| Minutos por cuarto | ✅ Directo (léelos junto a los puntos) |
| Puntos per-36 en el cuarto cuarto | ❌ Rechazado — no hay tasas por cuarto, y no es un hueco |
| Marcador por cuartos de un partido | ✅ Directo |
| Rebotes en sábado, 5 temporadas | ⚠️ Tipo B — se responde con `n`, IC y aviso |
| Puntos contra los Lakers, 5 temporadas | ⚠️ Tipo B — n≈15, plantilla rival distinta |
| Puntos en sábado contra los Lakers | ⚠️ Tipo B — n≈2, insuficiente |
| Puntos en el último minuto | ❌ Tipo A — falta play-by-play |
| eFG% desde la esquina | ❌ Tipo A — faltan coordenadas de tiro |
| Mejor quinteto del equipo | ❌ Tipo A — faltan sustituciones |

---

## 5. Cómo ampliar el contrato

| Ampliación | Qué desbloquea | Coste |
|---|---|---|
| **Titularidad y DNP** (`BoxScoreTraditionalV3`) | `started`, `dnp_reason`, split titular/banquillo | ~6.600 peticiones, ~1,3 h. **Ojo**: devuelve también a los que no jugaron, y eso rompe la definición de `games_played` en `mv_player_season` — hay que corregirla en la misma migración |
| ~~**Shot charts** (`ShotChartDetail`)~~ | ~~Zonas de tiro~~ | **Nunca hará falta**: las coordenadas venían dentro del play-by-play, ya cargado. Se ahorró una pasada entera de ~3.000 peticiones |
| **Tracking** (`BoxScorePlayerTrackV3`) | Distancia recorrida, velocidad, emparejamientos defensivos | ~6.600 peticiones; solo desde 2013-14 |

Ninguna amplía el bloque B.

En el bloque B el límite es el calendario de la NBA — 82 partidos al año, y de
ahí no se sale. Ninguna fuente de datos lo arregla.
