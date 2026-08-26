import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { AgeCurve } from '../api/types'

/**
 * Las dos curvas de edad, juntas.
 *
 * Enseñarlas por separado no serviría de nada: el argumento ES la diferencia.
 * La transversal compara jugadores distintos y a los 36 solo quedan los que
 * envejecieron bien, así que el declive se le escapa de la muestra en vez de
 * aparecer en la curva.
 */
export function AgeCurveChart({ data }: { data: AgeCurve }) {
  const cs = new Map(data.cross_sectional.map((p) => [p.age, p.index]))
  const puntos = data.delta_curve.map((p) => ({
    age: p.age,
    delta: p.index,
    transversal: cs.get(p.age) ?? null,
  }))

  return (
    <div style={{ width: '100%', height: 280 }}>
      <ResponsiveContainer>
        <LineChart data={puntos} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="age"
            tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
            stroke="var(--border)"
          />
          <YAxis
            tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
            stroke="var(--border)"
            domain={['dataMin - 3', 'dataMax + 3']}
            tickFormatter={(v: number) => `${v.toFixed(0)}%`}
          />
          <ReferenceLine y={100} stroke="var(--border)" strokeDasharray="3 3" />
          <Tooltip
            contentStyle={{
              background: 'var(--surface-1)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(v, n) => [
              `${Number(v).toFixed(1)}%`,
              n === 'delta' ? 'Delta (intra-jugador)' : 'Transversal (sesgada)',
            ]}
            labelFormatter={(a) => `${a} años`}
          />
          <Line
            type="monotone"
            dataKey="transversal"
            stroke="var(--text-muted)"
            strokeDasharray="4 3"
            strokeWidth={1.5}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="delta"
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={{ r: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
