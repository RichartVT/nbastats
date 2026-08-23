import {
  CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer,
  Scatter, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { TrendBase } from '../api/types'
import { fmtDate, fmtStat, isPctStat } from '../lib/format'

/**
 * Trayectoria de un jugador a lo largo del tiempo.
 *
 * COLOR POR ÉNFASIS, NO POR CATEGORÍA. Hay dos capas, pero no son dos series
 * que compitan: los partidos sueltos son contexto y la media móvil es el
 * mensaje. Por eso los puntos van en gris de des-énfasis y solo la línea lleva
 * color.
 *
 * LA MEDIA MÓVIL ES SOLO PARA MIRAR. La pendiente, el intervalo y los tests
 * los calcula el backend sobre los valores CRUDOS. Regresar sobre una serie
 * suavizada autocorrelaciona los puntos y hunde el p-valor: con ruido puro,
 * esa vía declara "tendencia" tres veces más a menudo que la correcta.
 */
export function TrendChart({ trend }: { trend: TrendBase }) {
  const esPct = isPctStat(trend.stat)
  const escala = esPct ? 100 : 1

  const datos = trend.series.map((v, i) => ({
    i,
    fecha: trend.dates[i],
    valor: v * escala,
    media: trend.rolling[i] === null ? null : (trend.rolling[i] as number) * escala,
  }))

  if (datos.length === 0) {
    return <p style={{ color: 'var(--text-muted)' }}>Sin partidos suficientes.</p>
  }

  return (
    <div>
      <div style={{ height: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={datos} margin={{ top: 8, right: 16, bottom: 28, left: 4 }}>
            <CartesianGrid vertical={false} stroke="var(--gridline)" strokeWidth={1} />
            <XAxis
              dataKey="i"
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: 'var(--axis)' }}
              tickFormatter={(i) => (trend.dates[i] ? fmtDate(trend.dates[i]) : '')}
              minTickGap={56}
            />
            <YAxis
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={46}
              className="tabular"
              unit={esPct ? '%' : undefined}
            />

            {/* Escalones de nivel. Una recta describe mal una trayectoria que
                da un salto (lesión, traspaso, cambio de rol), así que se
                señalan en vez de dejar que la pendiente los promedie. */}
            {trend.change_points.map((cp) => (
              <ReferenceLine
                key={cp}
                x={cp}
                stroke="var(--series-2)"
                strokeWidth={1.5}
                label={{
                  value: 'cambio de nivel',
                  position: 'insideTopRight',
                  fill: 'var(--series-2)',
                  fontSize: 10,
                }}
              />
            ))}

            <Tooltip
              cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const p = payload[0].payload
                return (
                  <div
                    className="rounded-lg p-3 text-xs shadow-lg"
                    style={{
                      background: 'var(--surface-1)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <div className="mb-1 font-semibold">{fmtDate(p.fecha)}</div>
                    <div className="tabular">
                      Partido: {fmtStat(esPct ? p.valor / 100 : p.valor, trend.stat)}
                    </div>
                    {p.media !== null && (
                      <div className="tabular" style={{ color: 'var(--series-1)' }}>
                        Media móvil: {fmtStat(esPct ? p.media / 100 : p.media, trend.stat)}
                      </div>
                    )}
                  </div>
                )
              }}
            />

            <Scatter dataKey="valor" fill="var(--muted-mark)" shape="circle" r={2.5} />
            <Line
              type="monotone"
              dataKey="media"
              stroke="var(--series-1)"
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div
        className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 pl-2 text-xs"
        style={{ color: 'var(--text-secondary)' }}
      >
        <span className="inline-flex items-center gap-1.5">
          <span style={{ color: 'var(--muted-mark)' }} aria-hidden>●</span>
          Partido individual
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span style={{ color: 'var(--series-1)' }} aria-hidden>▬</span>
          Media móvil (solo visual)
        </span>
        {trend.change_points.length > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <span style={{ color: 'var(--series-2)' }} aria-hidden>│</span>
            Cambio de nivel
          </span>
        )}
      </div>
    </div>
  )
}
