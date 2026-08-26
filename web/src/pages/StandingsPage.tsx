import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Standing } from '../api/types'
import { Card, ErrorBox, Loading, Select } from '../components/Layout'
import { TeamLogo } from '../components/Media'
import { fmt, fmtSigned } from '../lib/format'


/** Racha como texto con signo: +4 son cuatro victorias seguidas. */
function racha(n: number | null): string {
  if (n === null || n === 0) return '—'
  return n > 0 ? `G${n}` : `P${Math.abs(n)}`
}

function TablaConferencia({ titulo, filas }: { titulo: string; filas: Standing[] }) {
  return (
    <Card title={titulo}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
              <th className="py-2 pr-2 text-right font-medium">#</th>
              <th className="py-2 pr-3 font-medium">Equipo</th>
              <th className="py-2 pr-3 text-right font-medium">W</th>
              <th className="py-2 pr-3 text-right font-medium">L</th>
              <th className="py-2 pr-3 text-right font-medium">%</th>
              <th className="py-2 pr-3 text-right font-medium">GB</th>
              <th className="py-2 pr-3 text-right font-medium">Casa</th>
              <th className="py-2 pr-3 text-right font-medium">Fuera</th>
              <th className="py-2 pr-3 text-right font-medium">Ú10</th>
              <th className="py-2 pr-3 text-right font-medium">Racha</th>
              <th className="py-2 text-right font-medium">Dif</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((t) => (
              <tr
                key={t.team_id}
                style={{
                  borderTop: '1px solid var(--border)',
                  // Línea de corte de playoffs: los 10 primeros entran en
                  // play-in o playoffs, del 11 en adelante están fuera.
                  ...(t.playoff_rank === 11
                    ? { borderTop: '2px solid var(--axis)' }
                    : {}),
                }}
              >
                <td
                  className="tabular py-2 pr-2 text-right"
                  style={{ color: 'var(--text-muted)' }}
                >
                  {t.playoff_rank}
                </td>
                <td className="py-2 pr-3">
                  <Link
                    to={`/equipo/${t.team_id}`}
                    className="inline-flex items-center gap-2 whitespace-nowrap hover:underline"
                    style={{ color: 'var(--series-1)' }}
                  >
                    <TeamLogo teamId={t.team_id} name={t.abbreviation} size={20} />
                    {t.full_name}
                  </Link>
                </td>
                <td className="tabular py-2 pr-3 text-right font-medium">{t.wins}</td>
                <td className="tabular py-2 pr-3 text-right">{t.losses}</td>
                <td className="tabular py-2 pr-3 text-right">{fmt(t.win_pct, 3)}</td>
                <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--text-secondary)' }}>
                  {t.games_back === 0 ? '—' : fmt(t.games_back, 1)}
                </td>
                <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--text-secondary)' }}>
                  {t.home_record}
                </td>
                <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--text-secondary)' }}>
                  {t.road_record}
                </td>
                <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--text-secondary)' }}>
                  {t.last_10}
                </td>
                <td className="tabular py-2 pr-3 text-right">{racha(t.current_streak)}</td>
                <td
                  className="tabular py-2 text-right"
                  style={{
                    color:
                      (t.diff_points_pg ?? 0) > 0
                        ? 'var(--status-good)'
                        : 'var(--status-critical)',
                  }}
                >
                  {fmtSigned(t.diff_points_pg, 1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs" style={{ color: 'var(--text-muted)' }}>
        La línea marca el corte del play-in: del 1 al 10.
      </p>
    </Card>
  )
}


export function StandingsPage() {
  // Las temporadas salen de `/catalog`, no de una constante: es literalmente lo
  // que el docstring de ese endpoint dice que hay que hacer, y esta pantalla
  // llevaba la lista escrita a mano.
  const catalogo = useQuery({ queryKey: ['catalog'], queryFn: api.catalog })
  const temporadas = catalogo.data?.seasons ?? []
  const [elegida, setSeason] = useState('')
  const season = elegida || temporadas[0] || ''

  const { data, isLoading, error } = useQuery({
    queryKey: ['standings', season],
    queryFn: () => api.standings(season),
    enabled: Boolean(season),
    placeholderData: (prev) => prev,
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Clasificación</h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
          Posiciones oficiales de la NBA, con los desempates ya aplicados.
        </p>
      </div>

      <Select
        label="Temporada"
        value={season}
        onChange={setSeason}
        options={temporadas.map((t) => ({ value: t, label: t }))}
      />

      {error ? (
        <ErrorBox error={error} />
      ) : isLoading && !data ? (
        <Loading />
      ) : (
        <div className="space-y-6">
          <TablaConferencia
            titulo="Conferencia Este"
            filas={(data ?? []).filter((t) => t.conference === 'East')}
          />
          <TablaConferencia
            titulo="Conferencia Oeste"
            filas={(data ?? []).filter((t) => t.conference === 'West')}
          />
        </div>
      )}
    </div>
  )
}
