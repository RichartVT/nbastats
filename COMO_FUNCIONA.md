# Cómo funciona

Este documento explica **el recorrido de un dato**, desde que se pide a la NBA hasta que aparece
como un número en pantalla, y sobre todo **cómo se calcula un pronóstico**. No es el registro
histórico —eso es `BITACORA.md`— ni el contrato de qué se puede preguntar —eso es
`CAPABILITIES.md`—: es el mapa.

---

## 1. La forma del sistema

```
   NBA (stats.nba.com)
        │  ingesta idempotente y reanudable
        ▼
   PostgreSQL ── tablas de hechos ──► columnas derivadas ──► vistas materializadas
        │                             (derive.sql)          (views.sql)
        ▼
   analysis/  ← PURO: recibe listas de números, devuelve dataclasses. No sabe que hay una base.
        │
        ▼
   api/      ← el SQL vive aquí. Compone: lee filas, llama a `analysis`, devuelve JSON.
        │
        ▼
   web/      ← React. Los menús salen de `/catalog`, no de constantes.
```

**La regla que sostiene todo lo demás:** `analysis/` no importa SQLAlchemy ni conoce la base de
datos. Recibe listas de números y devuelve objetos. Por eso cada motor se puede probar contra
mundos sintéticos donde la verdad se conoce — que es como se descubrió que el método delta corrige
el sesgo de supervivencia y que la calidad de tiro no mejora nada.

La única excepción declarada es `analysis/backtest.py`, que orquesta el walk-forward: recibe las
filas ya leídas y devuelve las filas a escribir. La E/S se queda fuera, en `ratings_job.py`.

---

## 2. Qué hay cargado

| | |
|---|---|
| Temporadas | 5 (2021-22 → 2025-26) |
| Partidos | 6.602 |
| Filas equipo-partido | 13.204 |
| Filas jugador-partido | 172.477 (140.932 apariciones + 31.545 DNP) |
| Filas jugador-partido-cuarto | 481.863 |
| Eventos de play-by-play | 3.251.908 |
| Jugadores con biografía | 1.030 |
| Tamaño en disco | 860 MB (de los cuales 576 MB son play-by-play) |

---

## 3. De dónde sale cada cosa

La lección que este proyecto aprendió tres veces: **antes de pagar una pasada por partido,
comprobar si el endpoint masivo admite el filtro.**

| Qué | Endpoint | Coste |
|---|---|---|
| Box scores de una temporada | `PlayerGameLogs` / `TeamGameLogs` | ~25 peticiones **por temporada** |
| De dónde salen los puntos | `TeamGameLogs(MeasureType="Misc")` | 15 peticiones para las 5 temporadas |
| Rendimiento por cuarto | `PlayerGameLogs(Period=N)` | **93** peticiones, no 26.400 |
| Marcador por periodo, árbitros | `BoxScoreSummaryV3` | 1 por partido |
| Play-by-play (con coordenadas) | `PlayByPlayV3` | 1 por partido |
| Titularidad y motivo de DNP | `BoxScoreTraditionalV3` | 1 por partido |

Las tres últimas son inevitablemente por partido. El play-by-play trae las coordenadas de cada
tiro, lo que hizo innecesario `ShotChartDetail`.

**Correr siempre desde una máquina doméstica.** `stats.nba.com` descarta conexiones desde IPs de
centro de datos.

---

## 4. Columnas derivadas y vistas

Hay tres capas de cálculo dentro de la base, y el orden importa:

1. **Tablas de hechos** — lo que la NBA devuelve, sin transformar.
2. **`derive.sql`** — lo que depende de *otros* partidos y por eso no puede venir en la ingesta:
   días de descanso, back-to-back, el récord con el que se llegaba al partido, y el índice de
   ausencias.
3. **`views.sql`** — vistas materializadas con las tasas ya calculadas (per-36, TS%, eFG%,
   per-100).

**Un filtro de esa capa merece explicación**: `mv_player_game_rates` excluye las filas con
`dnp_reason`. Un DNP es un hecho y se guarda, pero **no es una aparición**, y todo lo que cuelga de
esa vista lo contaría — `games_played` es un `COUNT(*)`. Sin ese filtro, cargar la titularidad
habría inflado `games_played` en 28.619 partidos y hundido el índice de ausencias de 72,5 a 43,4
minutos de media, sin dar un solo error.

---

## Cómo sale un pronóstico

Cinco pasos. Ninguno usa información que no estuviera disponible antes del salto inicial.

### Paso 1 — De puntos a eficiencia

El marcador depende del ritmo: 110 puntos en 105 posesiones no valen lo mismo que en 95. Todo
arranca normalizando a **puntos por 100 posesiones**.

### Paso 2 — Ratings ajustados por rival

Un +5 de diferencial contra el calendario más duro y otro contra el más blando no valen lo mismo.
Una fila por equipo y partido:

```
anotados_por_100 = μ + O(equipo) − D(rival) + h·(local ? +1 : −1)
```

`O` es cuánto anota un equipo por encima de la media; `D`, cuánto resta a lo que le anotan (más
alto = mejor defensa). Se resuelve por mínimos cuadrados con **filas aumentadas**: se añaden filas
artificiales `√λ·coef = √λ·prior` que penalizan los efectos de equipo y dejan libres `μ` y la
localía. Es forma cerrada — no hay optimizador que pueda no converger — y se ve exactamente qué se
penaliza.

**λ no está inventado: es la `k` medida.** `analysis/stability.py` descompone la varianza y dice
cuántos partidos hacen falta para que el dato propio de un equipo pese lo mismo que la media de la
liga. Para el rating ofensivo y defensivo sale ~13, y ese es λ.

**El prior entre temporadas.** Cada temporada arranca con lo que los equipos eran al cerrar la
anterior, encogido por su persistencia medida sobre 120 pares equipo-transición:

| | ρ | Se hereda | λ del prior |
|---|---|---|---|
| Ataque | +0,446 | ×0,450 | 16,2 |
| Defensa | +0,517 | ×0,554 | 17,7 |

La defensa se hereda más que el ataque: depende más del sistema y menos de quién tenga la mano
caliente. Y **λ del prior es mayor que λ contra cero**, que parece al revés y no lo es: λ lleva la
varianza entre equipos en el denominador, y al encoger hacia el prior lo que queda por explicar es
solo τ²(1−ρ²). Un prior informativo merece más peso que la nada.

Sin prior, un equipo no tiene rating hasta su partido 20 (`MIN_PREVIOS`) y eso dejaba 1.246
partidos sin pronóstico. Con prior, el umbral es 0.

### Paso 3 — Las cuatro variables del partido

Solo cuatro, y a propósito. Con ~4.600 partidos de entrenamiento y σ≈13 puntos de ruido por
partido, cada variable extra compra una milésima de log-loss y vende sobreajuste.

| Variable | Qué es |
|---|---|
| `rating_diff` | Neto del local − neto del visitante, **sin** localía |
| `home` | 1 en pista propia, 0 en sede neutral |
| `rest_diff` | Días de descanso del local − del visitante, **acotado a 4** |
| `b2b_diff` | +1 si solo el visitante juega su segundo partido en dos días, −1 si solo el local |

El descanso se acota porque entre 4 y 12 días no hay diferencia práctica, y sin acotar los parones
de temporada dominarían el coeficiente.

**`rest_diff` y `b2b_diff` no son redundantes**, aunque salgan de la misma resta: 0 días de descanso
**es** un back-to-back, siempre. El descanso entra lineal y el back-to-back es el **salto** extra de
pasar de 1 día a 0. Por eso el simulador deriva el segundo del primero en vez de ofrecer dos
casillas que permitirían pedir estados que no existen.

### Paso 4 — Dos rutas que tienen que estar de acuerdo

Es la regla de la casa, la misma que exige Mann-Kendall **y** un intervalo que excluya el cero
antes de declarar una tendencia.

1. **Regresión logística** sobre el resultado. Solo ve el signo.
2. **Regresión lineal sobre el margen**, que da μ y σ, y de ahí `P = Φ(μ/σ)`. Ve la magnitud y
   asume normalidad.

Son independientes. Si coinciden, la probabilidad es creíble; si discrepan más de 3 puntos, el
modelo **lo dice** en vez de elegir la que más guste. La probabilidad publicada es la media de las
dos. Hoy discrepan en 113 de 4.906 partidos (2,3 %).

**Los coeficientes vigentes** (temporada 2025-26, 4.603 partidos de entrenamiento, σ=13,78):

| | Margen | Logística |
|---|---|---|
| Constante | +1,9143 | +0,2297 |
| `rating_diff` | +1,1695 | +0,1516 |
| `rest_diff` | +0,2828 | +0,0567 |
| `b2b_diff` | +2,5310 | +0,3118 |

`home` sale 0,0000 y no es un fallo: en el backtest no hay sedes neutrales, así que esa columna es
constante, colisiona con la constante y se descarta. **El efecto de la localía vive en la
constante** — de ahí que valga +1,91 puntos. En sede neutral el endpoint resta la constante y
avisa de que está extrapolando a un sitio donde el modelo no se entrenó.

**Regla de bolsillo para auditar a ojo:** cerca del 50 %, `dP/dmargen = φ(0)/σ ≈ 0,029`. Cada punto
de margen esperado vale unos **3 puntos porcentuales** de probabilidad.

### Paso 5 — El desglose

Cada barra es un coeficiente por su variable, así que **la suma es el margen esperado por
construcción**, no porque se haya cuadrado a mano. La respuesta no redondea: quien sume los
componentes obtiene el número exacto.

Los coeficientes se guardan en `model_runs` cuando se ajustan, y `/predict` **reconstruye** el
modelo desde ahí en vez de reimplementar la fórmula. No es un detalle de estilo: una versión
anterior tenía dos multiplicadores escritos a mano y llegaba a desviarse 6 puntos porcentuales del
modelo que se validó, sin dar ningún error. Hay un test que exige que los coeficientes guardados
reproduzcan las 4.906 probabilidades almacenadas.

---

## 5. Cómo se evita ver el futuro

Es el fallo más fácil de cometer y el más difícil de detectar: no da error, sube las métricas y las
deja mintiendo. Se evita en **dos niveles**:

1. **Los ratings de un partido se ajustan solo con partidos de fecha anterior.** Los del mismo día
   no se ven entre sí, porque en la realidad tampoco.
2. **El modelo de probabilidad se entrena solo con temporadas anteriores.** La primera temporada
   cargada no se puntúa: no tiene con qué entrenarse.

El prior entre temporadas no rompe esto: sale de los ratings de cierre de la temporada *anterior*,
que para la siguiente son pasado. Hay un test que altera el resultado de los últimos 40 partidos y
exige que **ni una sola variable** de los partidos anteriores cambie — y se comprobó que no es
vacuo introduciendo la fuga a propósito.

**Qué NO entra en el pronóstico, y por qué.** El índice de ausencias es la señal con más recorrido
de todas las medidas (21 puntos porcentuales), y está deliberadamente fuera: que un jugador no
aparezca en el box score se sabe *después* del partido, y los "minutos habituales" se calculan con
la temporada entera. Hay un test que falla si alguien lo añade a `GameFeatures`. En el simulador se
ofrece como entrada del usuario, pero en un bloque **aparte** del número calibrado.

**Cuánto valdría si fuera prospectivo, medido:** rehaciendo el índice sin fuga —minutos habituales
solo de partidos anteriores— y quedándose solo con las ausencias conocibles antes del salto
inicial, el acierto pasa de 65,76 % a **67,24 %** (+1,49 pp, p=0,0003). Curiosamente **el parte de
lesiones bate a la alineación real**: el 20 % de los minutos ausentes son descartes técnicos, que
son ruido y no señal, y el parte los filtra por construcción.

---

## 6. Cómo se valida

- **Contra líneas base tontas**, no contra sí mismo: "siempre gana el local" (55,56 %) y "gana el de
  mejor récord" (64,64 %).
- **Calibración publicada siempre con su suelo de ruido.** Bajo calibración perfecta el ECE no es
  cero; con esta muestra el suelo es 0,0180.
- **Pendiente e intercepto de Cox**, que detectan exceso o falta de confianza mejor que un diagrama
  de diez tramos.
- **McNemar sobre pares discordantes** para comparar con la línea base, no diferencias de
  porcentajes sueltas.

---

## 7. Los otros motores

| Módulo | Qué contesta | Estado |
|---|---|---|
| `ratings.py` | Fuerza ajustada por rival | En producción |
| `forecast.py` | Probabilidad de victoria, dos rutas | En producción |
| `calibration.py` | ¿Significa lo que dice? | En producción |
| `stability.py` | ¿Cuántos partidos para creerse un dato? | `/stability` |
| `expected.py` | De dónde salieron los puntos | `/games/{id}/expected` |
| `absences.py` | Cuánta rotación faltaba | Ficha de partido y simulador |
| `trends.py` | Tendencias, y la curva de edad por método delta | `/age-curve` |
| `reliability.py` | Encogimiento y control de falsos positivos | Transversal |
| `rates.py` | per-36, TS%, eFG%, Game Score | **No lo usa la API** — es la verificación cruzada contra el SQL |

---

## 8. Operación

```bash
uv run nbastats status          # qué hay cargado
uv run nbastats daily           # actualización diaria completa
uv run nbastats build-ratings   # reajusta ratings, modelo y predicciones (sin red)
uv run nbastats refresh         # recalcula derivadas y refresca vistas
```

**`daily` lo hace todo**, incluidos el play-by-play de los partidos que falten y el reajuste de
ratings. Esto último no es opcional: las consultas resuelven la temporada con
`COALESCE(:season, MAX(...))`, así que sin reajustar, el primer día de una temporada nueva la
aplicación serviría la anterior **como si fuera la actual**. Por eso `/ratings` devuelve
`fitted_at`, `games_since_fit` e `is_stale`, y la pantalla lo enseña.

---

## 9. Cómo leer los números de esta aplicación

Tres costumbres que no son decorativas:

1. **Nada se afirma sin su incertidumbre.** Un split que no se distingue del azar se enseña
   encogido hacia la media y etiquetado como tal.
2. **Los resultados negativos se publican.** Dos motores se probaron con su criterio fijado de
   antemano y fallaron; están documentados con sus cifras en vez de escondidos.
3. **Lo que no se puede contestar está escrito**, en `CAPABILITIES.md`, separando lo que falta por
   datos de lo que falta por muestra.
