import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { AgeCurveChart } from '../components/AgeCurveChart'
import { Card, ErrorBox, Loading, Select } from '../components/Layout'
import { ReliabilityBadge } from '../components/Reliability'
import { fmt, fmtSigned } from '../lib/format'

/**
 * Cuánto declive por edad es NORMAL.
 *
 * Va en esta pantalla y no en otra porque es la pregunta que da sentido a la
 * lista de al lado: sin ella, "este jugador cae" no se distingue de "este
 * jugador tiene 34 años y le pasa lo que a todos".
 */
function CurvaDeEdad({ stat, label }: { stat: string; label: string }) {
  const c = useQuery({
    queryKey: ['ageCurve', stat],
    queryFn: () => api.ageCurve(stat),
    retry: false,
  })
  if (!c.data) return null
  const d = c.data

  return (
    <Card
      title="¿Cuánto declive es normal a esa edad?"
      subtitle={`${label} · ${d.n_transitions.toLocaleString('es-ES')} pares de temporadas consecutivas del mismo jugador`}
    >
      <AgeCurveChart data={d} />

      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs">
        <span className="flex items-center gap-1.5" style={{ color: 'var(--text-secondary)' }}>
          <span style={{ width: 14, height: 2, background: 'var(--series-1)' }} />
          Delta — cada jugador contra sí mismo
        </span>
        <span className="flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
          <span
            style={{
              width: 14,
              height: 0,
              borderTop: '2px dashed var(--text-muted)',
            }}
          />
          Transversal — la sesgada
        </span>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
              <th className="py-1 pr-3 font-medium">Tramo de edad</th>
              <th className="py-1 pr-3 text-right font-medium">Cambio por temporada</th>
              <th className="py-1 pr-3 text-right font-medium">Pares</th>
              <th className="py-1 font-medium">¿Se distingue de cero?</th>
            </tr>
          </thead>
          <tbody>
            {d.bands.map((b) => (
              <tr key={b.label} style={{ borderTop: '1px solid var(--border)' }}>
                <td className="py-1.5 pr-3">{b.label}</td>
                <td
                  className="tabular py-1.5 pr-3 text-right font-medium"
                  style={{
                    color:
                      !b.distinguishable
                        ? 'var(--text-muted)'
                        : b.mean_change > 0
                          ? 'var(--status-good)'
                          : 'var(--status-critical)',
                  }}
                >
                  {b.mean_change > 0 ? '+' : ''}
                  {b.mean_change.toFixed(3)}
                </td>
                <td className="tabular py-1.5 pr-3 text-right" style={{ color: 'var(--text-muted)' }}>
                  {b.n_transitions}
                </td>
                <td className="py-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
                  {b.distinguishable ? 'Sí' : 'No — cabe dentro del ruido'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
        {d.caveat} {d.note}
      </p>
    </Card>
  )
}

export function LeadersPage() {
  const [direccion, setDireccion] = useState('declining')
  const [stat, setStat] = useState('pts_per_36')
  const [minPartidos, setMinPartidos] = useState('150')

  const catalogo = useQuery({ queryKey: ['catalog'], queryFn: api.catalog })
  const { data, isLoading, error } = useQuery({
    queryKey: ['leaders', direccion, stat, minPartidos],
    queryFn: () => api.leaders(direccion, stat, Number(minPartidos), 25),
    placeholderData: (prev) => prev,
  })

  // Solo tasas: comparar totales por partido entre jugadores confunde "juega
  // peor" con "juega menos minutos", que es justo lo que hay que separar.
  const opcionesStat = (catalogo.data?.stats ?? [])
    .filter((s) => s.is_rate)
    .map((s) => ({ value: s.value, label: s.label }))

  const declive = direccion === 'declining'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">
          Jugadores {declive ? 'en declive' : 'al alza'}
        </h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
          Pendiente de la trayectoria a lo largo de las 5 temporadas, en tasas
          normalizadas por minutos.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <Select
          label="Dirección"
          value={direccion}
          onChange={setDireccion}
          options={[
            { value: 'declining', label: 'En declive' },
            { value: 'rising', label: 'Al alza' },
          ]}
        />
        <Select label="Estadística" value={stat} onChange={setStat} options={opcionesStat} />
        <Select
          label="Mínimo de partidos"
          value={minPartidos}
          onChange={setMinPartidos}
          options={[
            { value: '100', label: '100' },
            { value: '150', label: '150' },
            { value: '200', label: '200' },
            { value: '250', label: '250' },
          ]}
        />
      </div>

      {error ? (
        <ErrorBox error={error} />
      ) : isLoading && !data ? (
        <Loading />
      ) : data ? (
        <>
          <Card
            title={`${data.players_significant} jugadores con tendencia real`}
            subtitle={`de ${data.players_scanned} analizados · ${data.stat_label}`}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
                    <th className="py-2 pr-4 font-medium">Jugador</th>
                    <th className="py-2 pr-4 text-right font-medium">Por temporada</th>
                    <th className="py-2 pr-4 text-right font-medium">IC 95%</th>
                    <th className="py-2 pr-4 text-right font-medium">Últimos 25</th>
                    <th className="py-2 pr-4 text-right font-medium">q</th>
                    <th className="py-2 font-medium">Muestra</th>
                  </tr>
                </thead>
                <tbody>
                  {data.leaders.map((l) => (
                    <tr key={l.player_id} style={{ borderTop: '1px solid var(--border)' }}>
                      <td className="py-2 pr-4">
                        <Link
                          to={`/jugador/${l.player_id}`}
                          className="font-medium hover:underline"
                          style={{ color: 'var(--series-1)' }}
                        >
                          {l.player_name}
                        </Link>
                      </td>
                      <td
                        className="tabular py-2 pr-4 text-right font-semibold"
                        style={{
                          color: declive ? 'var(--status-critical)' : 'var(--status-good)',
                        }}
                      >
                        {fmtSigned(l.slope_per_season)}
                      </td>
                      <td
                        className="tabular py-2 pr-4 text-right text-xs"
                        style={{ color: 'var(--text-secondary)' }}
                      >
                        {fmtSigned(l.ci95_low)} a {fmtSigned(l.ci95_high)}
                      </td>
                      <td className="tabular py-2 pr-4 text-right">
                        {fmt(l.current_value, 1)}
                      </td>
                      <td
                        className="tabular py-2 pr-4 text-right text-xs"
                        style={{ color: 'var(--text-secondary)' }}
                      >
                        {l.q_value < 0.0001 ? '<0.0001' : l.q_value.toFixed(4)}
                      </td>
                      <td className="py-2">
                        <ReliabilityBadge reliability={l.reliability} n={l.n} />
                      </td>
                    </tr>
                  ))}
                  {data.leaders.length === 0 && (
                    <tr>
                      <td
                        colSpan={6}
                        className="py-6 text-center"
                        style={{ color: 'var(--text-muted)' }}
                      >
                        Ningún jugador supera el umbral con estos filtros.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          <p
            className="text-xs leading-relaxed"
            style={{ color: 'var(--text-muted)' }}
          >
            {data.caveat}
          </p>
        </>
      ) : null}

      <CurvaDeEdad
        stat={stat}
        label={opcionesStat.find((o) => o.value === stat)?.label ?? stat}
      />
    </div>
  )
}
