import {
  CartesianGrid, ErrorBar, ReferenceLine, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { SplitsResponse } from '../api/types'
import { fmtStat, isPctStat } from '../lib/format'

/**
 * Gráfico de puntos con bigotes de intervalo de confianza.
 *
 * POR QUÉ ESTA FORMA Y NO BARRAS. Una barra afirma que el trayecto desde cero
 * significa algo, y en un promedio de rebotes no significa nada: nadie parte de
 * cero. Peor aún, una barra grande se lee como "mucho" aunque su intervalo de
 * confianza sea enorme. El punto con bigotes hace visualmente obvio lo único
 * que importa aquí: **si el intervalo cruza la línea de referencia, no hay
 * nada que contar.**
 *
 * COLOR POR ÉNFASIS, NO POR CATEGORÍA. Los niveles no son entidades distintas
 * que haya que distinguir entre sí — son el mismo jugador en circunstancias
 * distintas. Usar 7 colores para 7 días gastaría el canal de color en
 * información que el eje ya da, y haría que los 7 parecieran igual de reales.
 * Aquí el color codifica otra cosa: azul = se distingue del azar, gris = no.
 */
export function SplitsChart({ data }: { data: SplitsResponse }) {
  const esPct = isPctStat(data.stat)
  const escala = esPct ? 100 : 1

  const puntos = data.splits
    .filter((s) => s.value !== null && s.n > 0)
    .map((s) => ({
      label: s.label,
      valor: (s.value ?? 0) * escala,
      // ErrorBar espera desplazamientos respecto al punto, no absolutos.
      error: [
        Math.max(0, ((s.value ?? 0) - (s.ci95_low ?? s.value ?? 0)) * escala),
        Math.max(0, ((s.ci95_high ?? s.value ?? 0) - (s.value ?? 0)) * escala),
      ] as [number, number],
      n: s.n,
      distinguishable: s.distinguishable,
      raw: s.raw_mean,
      note: s.note,
    }))

  if (puntos.length === 0) {
    return <p style={{ color: 'var(--text-muted)' }}>Sin datos para este split.</p>
  }

  const baseline = (data.splits.find((s) => s.baseline !== null)?.baseline ?? 0) * escala

  // El dominio se calcula sobre los EXTREMOS DE LOS BIGOTES, no sobre los
  // puntos: si se calcula sobre los valores, los intervalos se salen del eje y
  // se recortan justo la parte que hay que leer. Se redondea a enteros para que
  // las marcas no salgan como "32.663399999999996".
  const limites = puntos.flatMap((p) => [p.valor - p.error[0], p.valor + p.error[1]])
  const dominio: [number, number] = [
    Math.floor(Math.min(...limites, baseline) - 0.5),
    Math.ceil(Math.max(...limites, baseline) + 0.5),
  ]

  return (
    // La altura crece con el número de niveles para que el eje de categorías
    // nunca se comprima ni se recorte (29 rivales no caben en 300px).
    <div style={{ height: Math.max(220, puntos.length * 46 + 86) }}>
      <ResponsiveContainer width="100%" height="100%">
        {/* El margen superior deja hueco a la etiqueta de la línea de
            referencia, que si no queda cortada por el borde del gráfico. */}
        <ScatterChart margin={{ top: 26, right: 30, bottom: 24, left: 8 }}>
          <CartesianGrid
            horizontal={false}
            stroke="var(--gridline)"
            strokeWidth={1}
          />
          <XAxis
            type="number"
            dataKey="valor"
            domain={dominio}
            tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--axis)' }}
            className="tabular"
            tickFormatter={(v: number) => (esPct ? `${v.toFixed(0)}%` : v.toFixed(0))}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={124}
            tick={{ fill: 'var(--text-secondary)', fontSize: 13 }}
            tickLine={false}
            axisLine={false}
            // Sin esto Recharts pinta la primera categoría abajo, y los días
            // salen de domingo a lunes. Un eje en orden antinatural hace que el
            // ojo busque patrones donde no los hay — justo lo contrario del
            // objetivo de esta vista.
            reversed
          />

          {/* La referencia contra la que se juzga todo lo demás: el promedio
              del jugador. Un punto cuyo intervalo la cruza no dice nada. */}
          <ReferenceLine
            x={baseline}
            stroke="var(--text-muted)"
            strokeWidth={1.5}
            label={{
              value: 'su promedio',
              position: 'top',
              fill: 'var(--text-muted)',
              fontSize: 11,
            }}
          />

          <Tooltip
            cursor={{ stroke: 'var(--gridline)' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const p = payload[0].payload
              return (
                <div
                  className="max-w-xs rounded-lg p-3 text-xs leading-relaxed shadow-lg"
                  style={{
                    background: 'var(--surface-1)',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                  }}
                >
                  <div className="mb-1 font-semibold">{p.label}</div>
                  <div style={{ color: 'var(--text-secondary)' }}>{p.note}</div>
                </div>
              )
            }}
          />

          <Scatter
            data={puntos}
            shape={(props: any) => {
              const { cx, cy, payload } = props
              const real = payload.distinguishable
              return (
                <g>
                  {/* Anillo de 2px del color de la superficie: separa el punto
                      del bigote sin dibujarle un borde encima. */}
                  <circle cx={cx} cy={cy} r={7} fill="var(--surface-1)" />
                  <circle
                    cx={cx}
                    cy={cy}
                    r={5}
                    fill={real ? 'var(--series-1)' : 'var(--muted-mark)'}
                  />
                </g>
              )
            }}
          >
            <ErrorBar
              dataKey="error"
              direction="x"
              width={5}
              strokeWidth={2}
              stroke="var(--muted-mark)"
            />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>

      <div
        className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 pl-2 text-xs"
        style={{ color: 'var(--text-secondary)' }}
      >
        <span className="inline-flex items-center gap-1.5">
          <span style={{ color: 'var(--series-1)' }} aria-hidden>●</span>
          Se distingue del azar
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span style={{ color: 'var(--muted-mark)' }} aria-hidden>●</span>
          Indistinguible del azar
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden style={{ color: 'var(--muted-mark)' }}>├─┤</span>
          Intervalo de confianza del 95%
        </span>
      </div>
    </div>
  )
}

/** Vista de tabla: el gemelo accesible del gráfico. Todo valor debe ser
 *  alcanzable sin depender del color ni del hover. */
export function SplitsTable({ data }: { data: SplitsResponse }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr style={{ color: 'var(--text-secondary)' }} className="text-left">
            <th className="py-2 pr-4 font-medium">Nivel</th>
            <th className="py-2 pr-4 text-right font-medium">n</th>
            <th className="py-2 pr-4 text-right font-medium">Media cruda</th>
            <th className="py-2 pr-4 text-right font-medium">Ajustada</th>
            <th className="py-2 pr-4 text-right font-medium">IC 95%</th>
            <th className="py-2 pr-4 text-right font-medium">q</th>
            <th className="py-2 font-medium">Veredicto</th>
          </tr>
        </thead>
        <tbody>
          {data.splits.map((s) => (
            <tr key={s.label} style={{ borderTop: '1px solid var(--border)' }}>
              <td className="py-2 pr-4">{s.label}</td>
              <td className="tabular py-2 pr-4 text-right">{s.n}</td>
              <td className="tabular py-2 pr-4 text-right" style={{ color: 'var(--text-secondary)' }}>
                {fmtStat(s.raw_mean, data.stat)}
              </td>
              <td className="tabular py-2 pr-4 text-right font-medium">
                {fmtStat(s.value, data.stat)}
              </td>
              <td className="tabular py-2 pr-4 text-right" style={{ color: 'var(--text-secondary)' }}>
                {s.ci95_low !== null && s.ci95_high !== null
                  ? `${fmtStat(s.ci95_low, data.stat)} – ${fmtStat(s.ci95_high, data.stat)}`
                  : '—'}
              </td>
              <td className="tabular py-2 pr-4 text-right" style={{ color: 'var(--text-secondary)' }}>
                {s.q_value.toFixed(3)}
              </td>
              <td className="py-2" style={{ color: 'var(--text-secondary)' }}>
                {s.distinguishable ? 'Diferencia real' : 'Ruido'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
