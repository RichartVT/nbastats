import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { TrendDirection } from '../api/types'
import { Card, ErrorBox, Loading, Select } from '../components/Layout'
import { NoiseWarning, ReliabilityBadge } from '../components/Reliability'
import { SplitsChart, SplitsTable } from '../components/SplitsChart'
import { TrendChart } from '../components/TrendChart'
import { fmt, fmtPct, fmtSigned } from '../lib/format'

const DIRECCION: Record<TrendDirection, { texto: string; color: string; icono: string }> = {
  alza: { texto: 'Al alza', color: 'var(--status-good)', icono: '▲' },
  declive: { texto: 'En declive', color: 'var(--status-critical)', icono: '▼' },
  estable: { texto: 'Estable', color: 'var(--text-secondary)', icono: '=' },
  indeterminada: { texto: 'Sin datos suficientes', color: 'var(--text-muted)', icono: '·' },
}

export function PlayerPage() {
  const { id } = useParams()
  const playerId = Number(id)

  const [stat, setStat] = useState('pts_per_36')
  const [dimension, setDimension] = useState('dow')
  const [verTabla, setVerTabla] = useState(false)

  const catalogo = useQuery({ queryKey: ['catalog'], queryFn: api.catalog })
  const jugador = useQuery({
    queryKey: ['player', playerId],
    queryFn: () => api.player(playerId),
  })
  const temporadas = useQuery({
    queryKey: ['seasons', playerId],
    queryFn: () => api.seasons(playerId),
  })
  const tendencia = useQuery({
    queryKey: ['trend', playerId, stat],
    queryFn: () => api.trend(playerId, stat),
    placeholderData: (prev) => prev,
  })
  const splits = useQuery({
    queryKey: ['splits', playerId, dimension, stat],
    queryFn: () => api.splits(playerId, dimension, stat),
    placeholderData: (prev) => prev,
  })

  if (jugador.error) return <ErrorBox error={jugador.error} />
  if (!jugador.data) return <Loading />

  const p = jugador.data
  const opcionesStat = (catalogo.data?.stats ?? []).map((s) => ({
    value: s.value,
    label: s.label,
  }))
  const opcionesDim = (catalogo.data?.dimensions ?? []).map((d) => ({
    value: d.value,
    label: d.label,
  }))

  // Solo temporada regular, que es donde las comparaciones tienen sentido.
  const regulares = (temporadas.data ?? []).filter((t) => t.season_type === 'regular')

  return (
    <div className="space-y-6">
      {/* --- Cabecera --- */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{p.full_name}</h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
          {[
            p.position,
            p.age ? `${p.age} años` : null,
            p.height_cm ? `${p.height_cm} cm` : null,
            p.weight_kg ? `${p.weight_kg} kg` : null,
            p.teams.length ? p.teams.join(', ') : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </div>

      {/* --- Filtros: una sola fila arriba, no dentro de cada tarjeta --- */}
      <div className="flex flex-wrap items-center gap-4">
        <Select label="Estadística" value={stat} onChange={setStat} options={opcionesStat} />
        <Select label="Split por" value={dimension} onChange={setDimension} options={opcionesDim} />
      </div>

      {/* --- Tendencia --- */}
      <Card
        title="Trayectoria"
        subtitle={tendencia.data?.stat_label}
        right={
          tendencia.data && (
            <div className="flex items-center gap-3">
              <span
                className="inline-flex items-center gap-1.5 text-sm font-semibold"
                style={{ color: DIRECCION[tendencia.data.direction].color }}
              >
                <span aria-hidden>{DIRECCION[tendencia.data.direction].icono}</span>
                {DIRECCION[tendencia.data.direction].texto}
              </span>
              <ReliabilityBadge
                reliability={tendencia.data.reliability}
                n={tendencia.data.n}
              />
            </div>
          )
        }
      >
        {tendencia.error ? (
          <ErrorBox error={tendencia.error} />
        ) : !tendencia.data ? (
          <Loading />
        ) : (
          <div className="space-y-4">
            <TrendChart trend={tendencia.data} />

            {tendencia.data.direction !== 'indeterminada' && (
              <div className="grid gap-3 sm:grid-cols-3">
                <Metrica
                  etiqueta="Cambio por temporada"
                  valor={fmtSigned(tendencia.data.slope_per_season)}
                  detalle={`IC95 ${fmtSigned(tendencia.data.ci95_low)} a ${fmtSigned(
                    tendencia.data.ci95_high,
                  )}`}
                />
                <Metrica
                  etiqueta="Tau de Kendall"
                  valor={fmt(tendencia.data.tau)}
                  detalle="Fuerza de la tendencia (−1 a 1)"
                />
                <Metrica
                  etiqueta="Varianza explicada"
                  valor={fmtPct(tendencia.data.r_squared)}
                  detalle="Cuánto del rendimiento explica el paso del tiempo"
                />
              </div>
            )}

            <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
              {tendencia.data.note}
            </p>
          </div>
        )}
      </Card>

      {/* --- Splits --- */}
      <Card
        title={`Rendimiento por ${splits.data?.dimension_label?.toLowerCase() ?? '…'}`}
        subtitle={
          splits.data
            ? `${splits.data.stat_label} · ${splits.data.total_games} partidos`
            : undefined
        }
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
        {splits.error ? (
          <ErrorBox error={splits.error} />
        ) : !splits.data ? (
          <Loading />
        ) : (
          <div className="space-y-4">
            {!splits.data.any_distinguishable && (
              <NoiseWarning>
                <strong>No hay ningún patrón aquí.</strong> Las diferencias entre
                niveles son las que cabría esperar del azar. Los valores mostrados
                están ajustados hacia el promedio general del jugador, que es la
                estimación honesta cuando la muestra no da para más.
              </NoiseWarning>
            )}

            {verTabla ? (
              <SplitsTable data={splits.data} />
            ) : (
              <SplitsChart data={splits.data} />
            )}

            <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
              {splits.data.caveat}
            </p>
          </div>
        )}
      </Card>

      {/* --- Temporadas --- */}
      <Card title="Por temporada" subtitle="Temporada regular">
        {temporadas.isLoading ? (
          <Loading />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
                  <th className="py-2 pr-3 font-medium">Temp.</th>
                  <th className="py-2 pr-3 font-medium">Equipo</th>
                  <th className="py-2 pr-3 text-right font-medium">PJ</th>
                  <th className="py-2 pr-3 text-right font-medium">Min</th>
                  <th className="py-2 pr-3 text-right font-medium">PTS</th>
                  <th className="py-2 pr-3 text-right font-medium">REB</th>
                  <th className="py-2 pr-3 text-right font-medium">AST</th>
                  <th className="py-2 pr-3 text-right font-medium">PTS/36</th>
                  <th className="py-2 pr-3 text-right font-medium">TS%</th>
                </tr>
              </thead>
              <tbody>
                {regulares.map((t) => (
                  <tr
                    key={`${t.season_id}-${t.team}`}
                    style={{ borderTop: '1px solid var(--border)' }}
                  >
                    <td className="py-2 pr-3">{t.season_id}</td>
                    <td className="py-2 pr-3" style={{ color: 'var(--text-secondary)' }}>
                      {t.team}
                    </td>
                    <td className="tabular py-2 pr-3 text-right">{t.games_played}</td>
                    <td className="tabular py-2 pr-3 text-right">{fmt(t.min_per_game, 1)}</td>
                    <td className="tabular py-2 pr-3 text-right font-medium">
                      {fmt(t.pts_per_game, 1)}
                    </td>
                    <td className="tabular py-2 pr-3 text-right">{fmt(t.reb_per_game, 1)}</td>
                    <td className="tabular py-2 pr-3 text-right">{fmt(t.ast_per_game, 1)}</td>
                    <td className="tabular py-2 pr-3 text-right">{fmt(t.pts_per_36, 1)}</td>
                    <td className="tabular py-2 pr-3 text-right">{fmtPct(t.ts_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
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
      {/* Cifra suelta: figuras proporcionales, no tabulares. */}
      <div className="mt-0.5 text-xl font-semibold">{valor}</div>
      <div className="mt-0.5 text-xs" style={{ color: 'var(--text-muted)' }}>
        {detalle}
      </div>
    </div>
  )
}
