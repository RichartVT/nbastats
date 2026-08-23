import { useState } from 'react'
import type { SplitsBase, TrendBase, TrendDirection } from '../api/types'
import { Card, ErrorBox, Loading } from './Layout'
import { NoiseWarning, ReliabilityBadge } from './Reliability'
import { SplitsChart, SplitsTable } from './SplitsChart'
import { TrendChart } from './TrendChart'
import { fmt, fmtPct, fmtSigned } from '../lib/format'

/**
 * Trayectoria + splits, compartido por jugadores y equipos.
 *
 * Se extrajo cuando la ficha de equipo necesitó exactamente lo mismo que la de
 * jugador. Duplicarlo habría significado dos sitios donde recordar que un
 * resultado no distinguible se muestra atenuado y con aviso — y el día que uno
 * de los dos se olvidara, la aplicación estaría enseñando ruido como si fuera
 * un hallazgo.
 */

const DIRECCION: Record<TrendDirection, { texto: string; color: string; icono: string }> = {
  alza: { texto: 'Al alza', color: 'var(--status-good)', icono: '▲' },
  declive: { texto: 'En declive', color: 'var(--status-critical)', icono: '▼' },
  estable: { texto: 'Estable', color: 'var(--text-secondary)', icono: '=' },
  indeterminada: { texto: 'Sin datos suficientes', color: 'var(--text-muted)', icono: '·' },
}

function Metrica({
  etiqueta,
  valor,
  detalle,
}: {
  etiqueta: string
  valor: string
  detalle: string
}) {
  return (
    <div
      className="rounded-lg px-3.5 py-3"
      style={{ background: 'var(--surface-page)', border: '1px solid var(--border)' }}
    >
      <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
        {etiqueta}
      </div>
      {/* Cifra suelta: figuras proporcionales, nunca tabulares. */}
      <div className="mt-0.5 text-xl font-semibold">{valor}</div>
      <div className="mt-0.5 text-xs" style={{ color: 'var(--text-muted)' }}>
        {detalle}
      </div>
    </div>
  )
}

export function TrendCard({
  trend,
  error,
  titulo = 'Trayectoria',
}: {
  trend: TrendBase | undefined
  error?: unknown
  titulo?: string
}) {
  return (
    <Card
      title={titulo}
      subtitle={trend?.stat_label}
      right={
        trend && (
          <div className="flex items-center gap-3">
            <span
              className="inline-flex items-center gap-1.5 text-sm font-semibold"
              style={{ color: DIRECCION[trend.direction].color }}
            >
              <span aria-hidden>{DIRECCION[trend.direction].icono}</span>
              {DIRECCION[trend.direction].texto}
            </span>
            <ReliabilityBadge reliability={trend.reliability} n={trend.n} />
          </div>
        )
      }
    >
      {error ? (
        <ErrorBox error={error} />
      ) : !trend ? (
        <Loading />
      ) : (
        <div className="space-y-4">
          <TrendChart trend={trend} />
          {trend.direction !== 'indeterminada' && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Metrica
                etiqueta="Cambio por temporada"
                valor={fmtSigned(trend.slope_per_season)}
                detalle={`IC95 ${fmtSigned(trend.ci95_low)} a ${fmtSigned(trend.ci95_high)}`}
              />
              <Metrica
                etiqueta="Tau de Kendall"
                valor={fmt(trend.tau)}
                detalle="Fuerza de la tendencia (−1 a 1)"
              />
              <Metrica
                etiqueta="Varianza explicada"
                valor={fmtPct(trend.r_squared)}
                detalle="Cuánto del rendimiento explica el paso del tiempo"
              />
            </div>
          )}
          <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
            {trend.note}
          </p>
        </div>
      )}
    </Card>
  )
}

export function SplitsCard({
  splits,
  error,
}: {
  splits: SplitsBase | undefined
  error?: unknown
}) {
  const [verTabla, setVerTabla] = useState(false)

  return (
    <Card
      title={`Rendimiento por ${splits?.dimension_label?.toLowerCase() ?? '…'}`}
      subtitle={splits ? `${splits.stat_label} · ${splits.total_games} partidos` : undefined}
      right={
        <button
          onClick={() => setVerTabla((v) => !v)}
          className="rounded-md px-2.5 py-1.5 text-xs"
          style={{
            background: 'var(--surface-1)',
            color: 'var(--text-secondary)',
            border: '1px solid var(--border)',
          }}
        >
          {verTabla ? 'Ver gráfico' : 'Ver tabla'}
        </button>
      }
    >
      {error ? (
        <ErrorBox error={error} />
      ) : !splits ? (
        <Loading />
      ) : (
        <div className="space-y-4">
          {!splits.any_distinguishable && (
            <NoiseWarning>
              <strong>No hay ningún patrón aquí.</strong> Las diferencias entre
              niveles son las que cabría esperar del azar. Los valores mostrados
              están ajustados hacia el promedio general, que es la estimación
              honesta cuando la muestra no da para más.
            </NoiseWarning>
          )}
          {verTabla ? <SplitsTable data={splits} /> : <SplitsChart data={splits} />}
          <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            {splits.caveat}
          </p>
        </div>
      )}
    </Card>
  )
}
