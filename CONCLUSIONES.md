# Conclusiones actuales

Qué sabe hacer este sistema, **con el número al lado**, y qué haría falta para mejorarlo. Cuando
algo ha llegado a su techo, se dice — y se dice por qué.

Regla de lectura: si una afirmación no lleva cifra, es una opinión y está marcada como tal.

---

## 1. Pronóstico

### Lo que hace

Sobre **4.906 partidos fuera de muestra**, con los ratings reajustados por fecha y el modelo
entrenado solo con temporadas anteriores:

| Métrica | Modelo | Siempre local | Mejor récord |
|---|---|---|---|
| Acierto | **65,76 %** | 55,56 % | 64,64 % |
| Brier | **0,2133** | 0,248 | — |
| Log-loss | **0,6147** | 0,689 | — |
| Brier Skill Score | **0,1362** | 0 | — |

### Lo que se puede prometer y lo que no

**+1,1 puntos porcentuales sobre "gana el de mejor récord".** Real en el número, no concluyente al
5 % con esta muestra. El récord ya codifica fuerza y calendario; un rating bien hecho añade sobre
todo *cuánto* mejor, no *quién*.

**Donde sí aporta de forma concluyente es en el arranque de temporada.** En los 1.236 partidos que
antes no tenían pronóstico —menos de 20 partidos previos— el modelo acierta el **65,37 %** contra
el **59,79 %** del récord: **+5,6 pp con p = 6,6e-05** por McNemar sobre 293 pares discordantes.
Tiene mecanismo evidente: en octubre un récord de 3-1 no dice nada y el prior sí.

**Y las probabilidades significan lo que dicen.** Pendiente de calibración 1,071, intercepto 0,019,
ECE 0,0176 con un suelo de ruido de 0,0180 — es decir, **el desajuste no supera lo que esta muestra
puede detectar**.

### El modelo está en su techo, y se puede demostrar

Si el margen esperado de cada partido fuera **exacto**, con σ=13,81 el acierto máximo alcanzable
sería del **64,28 %**. El modelo acierta el **65,76 %**: está en el límite, y por encima de su
propio techo calculado porque su calibración es un pelo conservadora (pendiente 1,07), lo que hace
que ese cálculo se quede corto.

Lo que limita el acierto no es el modelo, es el juego: 13,8 puntos de ruido por partido frente a un
margen esperado medio de 5,3.

**Y sabe cuáles sabe**, que es el verdadero producto:

| Lo que dice el modelo | Partidos | Acierto real |
|---|---|---|
| 50-55 % (casi moneda) | 1.044 (21 %) | **52,4 %** |
| 55-65 % | 1.675 (34 %) | 60,1 % |
| 65-75 % | 1.280 (26 %) | 72,4 % |
| 75 %+ | 907 (18 %) | **82,2 %** |

Monótono en los cuatro tramos. Cuando dice que no lo sabe, tiene razón en no saberlo — y eso vale
más que el porcentaje de portada.

### Tampoco está limitado por datos

Medido entrenando el mismo modelo con 1, 2, 3 y 4 temporadas previas:

| Temporadas de entrenamiento | Partidos | Acierto | log-loss |
|---|---|---|---|
| 1 | 1.151 | 65,58 % | 0,6151 |
| 2 | 1.995 | 65,56 % | 0,6147 |
| 3 | 2.533 | **65,78 %** | 0,6146 |
| 4 | 2.764 | 65,76 % | 0,6146 |

**Multiplicar por 2,4 los datos compra +0,18 pp**, y la curva ya baja entre 3 y 4. El modelo tiene
cinco parámetros; con ~1.200 partidos están estimados de sobra. El cuello de botella es el ruido
irreducible: **σ = 13,78 puntos de margen por partido**.

**Consecuencia práctica: más historia no mejora el pronóstico.** Una mejora tendría que venir de
mejores *variables*, nunca de más temporadas. Está desarrollado en §5.

### Qué haría falta para mejorarlo

| Vía | Estado |
|---|---|
| Más temporadas | ❌ Descartado y medido (arriba) |
| Más variables buscando p<0,05 | ❌ Descartado por criterio: es pesca de patrones |
| `scikit-learn`, boosting, redes | ❌ Con 6.136 filas y σ≈13, la señal cabe en cinco coeficientes |
| **Parte de lesiones previo al partido** | ✅ **La única vía real: +1,49 pp medido (p=0,0003).** Ver §2 |
| Distancia de viaje y husos horarios | 🟡 ~30 filas estáticas. Expectativa honesta: sale nulo |
| Congelar en junio y predecir la temporada | ❌ Medido: 59,84 % contra 59,43 % del récord del año anterior. Ver §5 |

---

## 2. Ausencias: la señal más fuerte, y por qué no está en el pronóstico

Del **59,4 %** de victorias con la plantilla entera al **38,0 %** con más de 100 minutos habituales
fuera. Monótono en los seis tramos **y en el margen** (+4,2 a −4,4).

Controlando por la fuerza de ambos equipos, cada minuto ausente vale **0,0373 puntos de margen**
(EE 0,0031, t=11,9, p=2,3e-32) y añade **1,75 puntos de varianza explicada** sobre los ratings
solos.

**No está en el pronóstico, y es deliberado.** Por partida doble: quién no jugó se sabe *después*
del partido, y los "minutos habituales" se calculan con la temporada entera. Meterlo subiría las
métricas y las dejaría mintiendo. Hay un test que falla si alguien lo añade a `GameFeatures`.

### Qué haría falta

Los **partes de lesiones previos al partido**, que la NBA publica pero este sistema no ingiere.
Con ellos, la ausencia dejaría de ser información posterior y sería legítimamente predictiva. Es
**la única mejora del pronóstico con mecanismo demostrado y magnitud medida**:

| | Acierto | Brier | log-loss |
|---|---|---|---|
| Hoy | 65,76 % | 0,2133 | 0,6147 |
| + todas las ausencias | 66,84 % | 0,2104 | 0,6083 |
| **+ solo lo conocible antes del partido** | **67,24 %** | **0,2090** | **0,6051** |

**+1,49 puntos porcentuales, p=0,0003.** No más, y conviene saber por qué: los ratings actualizados
**ya absorben** buena parte de la información — un equipo que juega sin sus estrellas acumula peores
resultados y su rating baja solo. Las ausencias añaden lo que el rating aún no ha visto, la baja de
*esta* noche.

**El parte de lesiones bate a la alineación real, y no es una paradoja.** El 20 % de los minutos
ausentes son "decisión técnica": un jugador sano al que el entrenador no usó, muchas veces con el
partido decidido. Eso es ruido, no señal, y el parte lo filtra por construcción. Por eso usar solo
el 80 % conocible da **más** (+1,49 pp) que usarlo todo (+1,08 pp) — y por eso **no hace falta la
alineación anunciada**.

**Dos salvedades.** La medición reconstruye el parte desde el box score, o sea simula uno
*perfecto*; uno real tiene "duda" y "probable" y algunos acaban jugando, así que el número quedaría
algo por debajo. Y no hay endpoint histórico —la NBA lo publica en PDF—, así que solo podría
capturarse hacia adelante.

Advertencia: el umbral de "rotación" (10+ minutos de media) es una decisión convencional. Con otros
umbrales el recorrido del gradiente va de 15,1 a 23,5 pp, así que el titular depende de dónde se
ponga la raya.

---

## 3. Qué es habilidad y qué es la noche

Medido descontando el ruido de muestreo, no comparando dispersiones en bruto. `k` = partidos para
que la media propia de un equipo pese la mitad.

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
| Acierto en triples | **47,0** | Mixto |
| Acierto en los triples que **concedes** | **150,5** | Sobre todo azar |

**Conceder triples se estabiliza en 8 partidos; que entren necesita 150.** Es la misma jugada desde
los dos lados, y es la tabla de la que dependen los demás motores.

Hallazgo colateral: **de dónde salen los puntos de un equipo es identidad, no ruido** — pintura,
contraataque, tras pérdida y segunda oportunidad caen entre k=6,9 y k=15,2.

**Techo:** estas cifras son estables y no necesitan más datos. Más temporadas estrecharían los
intervalos sin mover las conclusiones.

---

## 4. Curva de edad

Corregida por método delta —cada jugador contra sí mismo entre temporadas consecutivas— sobre 809
transiciones:

| Tramo | Puntos/36 | Game Score | TS% | Minutos |
|---|---|---|---|---|
| 19-22 | +1,268 * | +1,477 * | +0,010 * | +1,425 * |
| 23-25 | +0,256 | +0,356 * | +0,003 | +0,149 |
| 26-28 | −0,034 | −0,042 | +0,001 | −0,303 |
| 29-31 | −0,103 | −0,477 * | +0,002 | −1,231 * |
| **32+** | **−0,615 \*** | **−0,987 \*** | −0,003 | **−2,008 \*** |

*(\* = se distingue de cero al 95 %)*

**La eficiencia de tiro no envejece.** Ni el TS% ni el eFG% ni las asistencias caen de forma
distinguible pasados los 32. Lo que cae son puntos, rebotes, Game Score y sobre todo **los minutos:
−2,0 por temporada**. No se pierde puntería ni criterio: se pierde el rol.

Contra la curva transversal, a los 34 años: **97,8 % del pico contra 89,3 %**. Validado en un mundo
sintético con la verdad conocida — a los 34 la verdad es 56,0 %, la transversal dice 70,3 % y la
delta 61,7 %: **corrige más de la mitad del error**.

### Techo actual: ESTE SÍ está limitado por muestra

Es el único análisis del sistema al que **más datos le harían bien de verdad**. Cada paso anual
tiene entre 20 y 90 jugadores y casi ninguno alcanza significación por separado; por eso se publica
por tramos y la curva se corta a los 34.

**Qué haría falta:** cargar temporadas anteriores llevaría las transiciones de 809 a ~1.700. Se
evaluó y **se descartó** —el coste es duplicar la base y 4-6 horas de descarga, y el resto del
sistema no gana nada— pero si algún día la curva de edad pasara a ser el análisis principal, esta
es la razón para reabrirlo.

**Y un límite que no se va con datos:** el método delta sigue subestimando el declive, porque un
jugador solo aporta el paso de t a t+1 si jugó las dos temporadas. Hay un test que **exige** que se
quede corto.

---

## 5. Lo que se probó y falló

Dos motores con su criterio fijado **antes** de mirar el resultado. Los dos fallaron y los dos se
publican enteros.

### "Debió ganar" — resultado negativo

La atribución es exacta y se publica: *"de los 4 puntos de derrota, el acierto en triples del rival
por encima de su norma aporta −12"* es aritmética verificable, con residuo **3,2e-14** sobre 400
partidos.

El **veredicto** no. La prueba era si el margen esperado mide la fuerza mejor que el margen real, y
sobre 150 equipos-temporada perdía en los cortes decisivos. La pantalla dice de dónde salieron los
puntos, sin decidir quién merecía ganar.

### Predecir una temporada entera desde junio — resultado negativo

Congelar todo al cerrar 2024-25 y predecir las 1.225 jornadas de 2025-26 sin un solo dato de esa
temporada. Constantes re-derivadas excluyéndola (persistencia 0,531/0,597 sobre 3 transiciones):

| | Acierto |
|---|---|
| Congelado en junio | 59,84 % |
| Mejor récord de 2024-25 | 59,43 % |
| Siempre gana el local | 55,43 % |

**+0,41 pp sobre la línea base**, y la calibración se rompe (pendiente 0,849 = exceso de confianza).
Congelar cuesta **seis puntos** frente al walk-forward normal.

Como proyección de temporada tampoco sirve: error medio de **9,68 victorias** contra las 10,30 de
"lo mismo que el año pasado", con fallos de hasta ±25.

La causa está medida: un equipo conserva **ρ≈0,5** de su identidad tras un verano, y lo que decide
el resto —traspasos, draft, desarrollo, lesiones— no existe en junio.

*(En este escenario las alineaciones sí valen +3,0 pp, precisamente porque no hay ratings
actualizados que absorban esa información. Sobre el sistema real valen +1,49 — ver §2.)*

### Calidad de tiro desde el play-by-play — resultado negativo

Separar *dónde* se tira de *si entra*, usando la localización de 1.168.487 tiros. RMSE fuera de
muestra:

| k | Margen real | Calidad de tiro |
|---|---|---|
| 10 | **5,003** | 5,869 |
| 20 | **4,300** | 5,367 |
| 30 | **4,261** | 5,241 |
| 41 | **4,254** | 5,491 |

**Pierde en los cuatro cortes, entre un 17 % y un 25 %.** Y se sabe por qué: la hipótesis tenía dos
mitades y solo una es cierta.

| | k | ρ entre temporadas |
|---|---|---|
| Calidad de tiro (la decisión) | 5,9 | +0,557 |
| Anotar por encima de lo esperado (el "acierto") | **14,2** | **+0,584** |

**El acierto condicionado a la localización no es ruido: es habilidad**, y persiste entre
temporadas más que la propia elección de tiro y más que el neto del equipo (+0,542). Sobrevive al
verano y a los traspasos. El estimador estaba tirando información.

Y remate: controlando por el rating, la habilidad de tiro **no añade nada** (ΔR² 0,003, p=0,619;
correlación +0,572 con el rating). Los ratings ya la llevaban dentro.

**Es la tercera vez que este proyecto tropieza con lo mismo.** El acierto de tiro es habilidad, y
ningún motor futuro debería normalizarlo.

---

## 6. Lo que no se puede contestar, y por qué

Separado en dos categorías, porque el remedio es distinto:

### Falta el dato (límite estructural)

- **Quién defendió a quién.** Requiere datos de seguimiento, que no están ni en el play-by-play.
- **Quintetos y on/off.** Los 319.323 eventos de sustitución tienen `sub_type` vacío y el jugador
  que ENTRA solo existe en el texto libre. Reconstruible, pero con una precisión que habría que
  medir — y el décimo quinteto de un equipo juega ~40 minutos en toda la temporada.
- **La lesión concreta y su duración.** La fuente dice el *tipo* (`DND - Injury/Illness`) pero no
  cuál ni cuánto. Y a un lesionado de larga duración ni lo lista en el acta: ahí el que lo caza es
  el índice de ausencias inferido.

### Falta muestra (límite estadístico)

- **Splits de una sola temporada.** Con 41 partidos en casa, ni la ventaja de campo —un efecto real
  y documentado— alcanza significación. Por eso el análisis de equipo abarca las cinco temporadas
  por defecto.
- **Calibración fina.** Con ~490 partidos por tramo no se puede detectar un desajuste menor de unos
  4 puntos porcentuales.
- **Curva de edad más allá de los 34.** Ver §4.

---

## 7. Resumen: qué se puede mejorar y qué no

| Área | Valor actual | ¿Techo? | Qué haría falta |
|---|---|---|---|
| Acierto del pronóstico | 65,76 % | **Sí** — está en el techo del ruido (64,3 % teórico) | Parte de lesiones previo: **+1,49 pp medido** |
| Calibración | ECE 0,0176 (suelo 0,0180) | **Sí** | Nada: ya está dentro del ruido |
| Cobertura del pronóstico | 4.906 de 6.136 | Casi | Los 1.323 de 2021-22 exigirían cargar 2020-21 |
| Efecto de las ausencias | 0,0373 pts/min | No | Partes de lesiones para hacerlo predictivo |
| Tabla de estabilidad | 14 componentes | **Sí** | Nada: estable y suficiente |
| Curva de edad | 809 transiciones | **No** | Más temporadas (evaluado y descartado) |
| Motor de "debió ganar" | Atribución exacta | **Cerrado** | Nada: el veredicto no sobrevivió su prueba |
| Calidad de tiro | — | **Cerrado** | Nada: el "acierto" resultó ser habilidad |

### La conclusión de una línea

**El pronóstico está en su techo con la información que hoy tiene.** Acierta el 65,76 % contra un
máximo alcanzable del 64,28 % dado su propio ruido, y sus probabilidades están calibradas dentro de
lo que la muestra puede detectar. No queda margen que recuperar con mejor modelo.

**La única mejora medida es el parte de lesiones previo al partido: +1,49 puntos porcentuales
(p=0,0003)**, hasta un 67,24 %. Ni más ni menos — y conviene no confundir dos cosas: en un partido
concreto, 100 minutos de rotación ausentes mueven la probabilidad unos 11 puntos, pero **eso no se
traduce en 11 puntos de acierto agregado**, porque los ratings actualizados ya absorben buena parte
de esa información antes de llegar ahí.

Todo lo demás que se ha probado —más temporadas, más variables, normalizar el acierto de tiro de
tres maneras distintas, congelar la temporada en junio— se midió y no aportó nada.
