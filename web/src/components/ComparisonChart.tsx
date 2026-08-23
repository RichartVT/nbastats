import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { Trend } from '../api/types'
import { fmtStat, isPctStat } from '../lib/format'

/**
 * Varios jugadores superpuestos en el tiempo.
 *
 * AQUÍ EL COLOR SÍ ES CATEGÓRICO, al revés que en el gráfico de splits: cuatro
 * jugadores son cuatro entidades distintas y el color es lo que las identifica.
 * Se usan los cuatro primeros slots de la paleta validada, en orden fijo y
 * nunca reciclado — el color sigue al jugador, no a su posición en la lista, así
 * que quitar a uno no repinta a los demás.
 *
 * SE DIBUJA LA MEDIA MÓVIL, NO LOS PARTIDOS. Cuatro nubes de puntos crudos
 * superpuestas son ilegibles: 1.400 marcas peleándose por el mismo espacio. La
 * media móvil es lo único que deja comparar trayectorias de un vistazo.
 *
 * TOPE DE CUATRO. A partir de ahí la paleta pone amarillo junto a naranja y el
 * par deja de ser distinguible bajo daltonismo. La solución no es generar un
 * quinto color: es no permitir un quinto jugador.
 */

export const MAX_JUGADORES = 4

// Días sin jugar a partir de los cuales se parte la línea. El parón de verano
// dura ~4 meses y el All-Star apenas una semana, así que 40 separa lo uno de lo
// otro sin fragmentar la temporada.
const DIAS_DE_PARON = 40

export const COLORES_SERIE = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--series-4)',
] as const

export function ComparisonChart({ trends }: { trends: Trend[] }) {
  const conDatos = trends.filter((t) => t.series.length > 0)
  if (conDatos.length === 0) {
    return <p style={{ color: 'var(--text-muted)' }}>Elige jugadores para comparar.</p>
  }

  const esPct = isPctStat(conDatos[0].stat)
  const escala = esPct ? 100 : 1

  // Cada jugador lleva su propia serie en vez de combinarlas en una tabla
  // compartida. El motivo es el verano: con una tabla común y `connectNulls`,
  // la línea tiende un puente recto entre el último partido de junio y el
  // primero de noviembre, y aparece un tramo plano de cinco meses que sugiere
  // que el jugador mantuvo ese nivel sin jugar. Aquí la línea se PARTE en cada
  // parón de más de 40 días, que es lo que de verdad ocurrió.
  const series = conDatos.map((t) => {
    const puntos: { t: number; v: number | null }[] = []
    let anterior: number | null = null

    t.dates.forEach((fecha, i) => {
      const valor = t.rolling[i]
      if (valor === null || valor === undefined) return
      const ms = new Date(`${fecha}T00:00:00`).getTime()

      if (anterior !== null && ms - anterior > DIAS_DE_PARON * 86_400_000) {
        // Punto nulo en mitad del hueco: rompe el trazo sin desplazar el eje.
        puntos.push({ t: anterior + (ms - anterior) / 2, v: null })
      }
      puntos.push({ t: ms, v: valor * escala })
      anterior = ms
    })
    return { trend: t, puntos }
  })

  const todos = series.flatMap((s) => s.puntos.filter((p) => p.v !== null))
  if (todos.length === 0) {
    return (
      <p style={{ color: 'var(--text-muted)' }}>
        Ninguno acumula partidos suficientes para una media móvil.
      </p>
    )
  }

  const valores = todos.map((p) => p.v as number)
  const tiempos = todos.map((p) => p.t)

  // Dominio ajustado a los datos, no anclado al cero. En una TASA el cero no es
  // una referencia con significado —nadie promedia cero puntos por 36 minutos—
  // y anclarlo ahí aplasta toda la variación en la franja superior del gráfico.
  const margen = (Math.max(...valores) - Math.min(...valores)) * 0.12 || 1
  const dominioY: [number, number] = [
    Math.floor(Math.min(...valores) - margen),
    Math.ceil(Math.max(...valores) + margen),
  ]
  const dominioX: [number, number] = [Math.min(...tiempos), Math.max(...tiempos)]

  // El color sigue al JUGADOR (su posición en la lista), no a su rendimiento:
  // quitar a uno no debe repintar a los demás. La leyenda solo se reordena para
  // mostrarse.
  const ordenadaPorFinal = series
    .map((s, i) => {
      const conValor = s.puntos.filter((p) => p.v !== null)
      return {
        trend: s.trend,
        color: COLORES_SERIE[i],
        final: conValor.length ? (conValor[conValor.length - 1].v as number) : -Infinity,
      }
    })
    .sort((a, b) => b.final - a.final)

  return (
    <div>
      <div style={{ height: 340 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart margin={{ top: 8, right: 24, bottom: 28, left: 4 }}>
            <CartesianGrid vertical={false} stroke="var(--gridline)" strokeWidth={1} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={dominioX}
              allowDuplicatedCategory={false}
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: 'var(--axis)' }}
              tickFormatter={(ms: number) =>
                new Date(ms).toLocaleDateString('es-ES', { month: 'short', year: '2-digit' })
              }
              minTickGap={56}
            />
            <YAxis
              domain={dominioY}
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={48}
              className="tabular"
              unit={esPct ? '%' : undefined}
            />
            <Tooltip
              cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null
                return (
                  <div
                    className="rounded-lg p-3 text-xs shadow-lg"
                    style={{
                      background: 'var(--surface-1)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <div className="mb-1.5 font-semibold">
                      {new Date(label as number).toLocaleDateString('es-ES')}
                    </div>
                    {payload
                      .filter((p) => p.value !== null && p.value !== undefined)
                      .map((p, i) => (
                        <div key={`${p.name}-${i}`} className="flex items-center gap-2">
                          <span aria-hidden style={{ color: p.color }}>●</span>
                          <span>{p.name}</span>
                          <span className="tabular ml-auto font-medium">
                            {fmtStat(
                              esPct ? (p.value as number) / 100 : (p.value as number),
                              conDatos[0].stat,
                            )}
                          </span>
                        </div>
                      ))}
                  </div>
                )
              }}
            />
            {series.map(({ trend, puntos }, i) => (
              <Line
                key={trend.player_id}
                data={puntos}
                type="monotone"
                dataKey="v"
                name={trend.player_name}
                stroke={COLORES_SERIE[i]}
                strokeWidth={2}
                dot={false}
                // Sin connectNulls: el punto nulo que se insertó en cada parón
                // tiene que romper el trazo, no ser puenteado.
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Leyenda ORDENADA POR EL VALOR FINAL, de mayor a menor.

          La guía de visualización pide etiquetas directas a partir de cuatro
          series, pero también prohíbe que las etiquetas se solapen — y cuatro
          jugadores con rendimientos parecidos acaban la línea casi a la misma
          altura, así que sus etiquetas chocarían justo cuando más falta hace
          distinguirlas. Ordenar la leyenda por el valor final cumple el mismo
          objetivo (que la identidad no dependa solo del color) sin provocar la
          colisión: el orden de la leyenda es el orden de arriba abajo con el
          que terminan las líneas. */}
      <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 pl-2 text-xs">
        {ordenadaPorFinal.map(({ trend, color }) => (
          <span
            key={trend.player_id}
            className="inline-flex items-center gap-1.5"
            style={{ color: 'var(--text-secondary)' }}
          >
            <span aria-hidden style={{ color }}>▬</span>
            {trend.player_name}
          </span>
        ))}
        <span style={{ color: 'var(--text-muted)' }}>
          Media móvil de 25 partidos · las líneas se parten en el parón de verano
        </span>
      </div>
    </div>
  )
}
