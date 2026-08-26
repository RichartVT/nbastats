import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Card, ErrorBox, Loading } from '../components/Layout'
import { TeamLogo } from '../components/Media'
import { fmtSigned } from '../lib/format'

export function TeamsPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['teams'], queryFn: () => api.teams() })

  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) return <Loading />

  const porConferencia = {
    East: data.filter((t) => t.conference === 'East'),
    West: data.filter((t) => t.conference === 'West'),
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Equipos</h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
          Récord de la temporada más reciente cargada. El puesto (#) es el de la
          conferencia: del 1 al 6 se entra directo a playoffs, del 7 al 10 se juega
          el play-in.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {(['East', 'West'] as const).map((conf) => (
          <Card key={conf} title={conf === 'East' ? 'Conferencia Este' : 'Conferencia Oeste'}>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
                  <th className="py-2 pr-2 text-right font-medium" title="Puesto en la conferencia">
                    #
                  </th>
                  <th className="py-2 pr-3 font-medium">Equipo</th>
                  <th className="py-2 pr-3 text-right font-medium">W-L</th>
                  <th className="py-2 pr-3 text-right font-medium" title="Récord como local">
                    Local
                  </th>
                  <th className="py-2 pr-3 text-right font-medium" title="Récord como visitante">
                    Visit.
                  </th>
                  <th className="py-2 text-right font-medium">Dif</th>
                </tr>
              </thead>
              <tbody>
                {porConferencia[conf]
                  .slice()
                  .sort((a, b) => (a.playoff_rank ?? 99) - (b.playoff_rank ?? 99))
                  .map((t) => (
                    <tr key={t.team_id} style={{ borderTop: '1px solid var(--border)' }}>
                      {/* El puesto se enseña, no solo se usa para ordenar: en una
                          tabla ordenada por récord no se distingue el 6º —que
                          entra directo— del 7º, que juega el play-in. */}
                      <td
                        className="tabular py-2 pr-2 text-right"
                        style={{
                          color:
                            (t.playoff_rank ?? 99) <= 6
                              ? 'var(--text-primary)'
                              : 'var(--text-muted)',
                        }}
                      >
                        {t.playoff_rank ?? '—'}
                      </td>
                      <td className="py-2 pr-3">
                        <Link
                          to={`/equipo/${t.team_id}`}
                          className="inline-flex items-center gap-2 hover:underline"
                          style={{ color: 'var(--series-1)' }}
                        >
                          <TeamLogo teamId={t.team_id} name={t.abbreviation} size={22} />
                          {t.full_name}
                        </Link>
                      </td>
                      <td className="tabular py-2 pr-3 text-right">
                        {t.wins}-{t.losses}
                      </td>
                      <td
                        className="tabular py-2 pr-3 text-right"
                        style={{ color: 'var(--text-secondary)' }}
                      >
                        {t.home_record ?? '—'}
                      </td>
                      <td
                        className="tabular py-2 pr-3 text-right"
                        style={{ color: 'var(--text-secondary)' }}
                      >
                        {t.road_record ?? '—'}
                      </td>
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
          </Card>
        ))}
      </div>
    </div>
  )
}
