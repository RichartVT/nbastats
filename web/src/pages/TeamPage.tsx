import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { Card, ErrorBox, Loading, Select } from '../components/Layout'
import { GameTypeBadge, PlayerPhoto, TeamLogo, WinLoss } from '../components/Media'
import { fmt, fmtDate, fmtSigned } from '../lib/format'

const TEMPORADAS = ['2025-26', '2024-25', '2023-24', '2022-23', '2021-22']

function Dato({ etiqueta, valor }: { etiqueta: string; valor: string | null }) {
  if (!valor) return null
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>
        {etiqueta}
      </dt>
      <dd className="mt-0.5 text-sm font-medium">{valor}</dd>
    </div>
  )
}

export function TeamPage() {
  const { id } = useParams()
  const teamId = Number(id)
  const [season, setSeason] = useState(TEMPORADAS[0])

  const equipo = useQuery({
    queryKey: ['team', teamId, season],
    queryFn: () => api.team(teamId, season),
    placeholderData: (prev) => prev,
  })
  const partidos = useQuery({
    queryKey: ['teamGames', teamId, season],
    queryFn: () => api.teamGames(teamId, [season]),
    placeholderData: (prev) => prev,
  })

  if (equipo.error) return <ErrorBox error={equipo.error} />
  if (!equipo.data) return <Loading />

  const t = equipo.data
  const conf = t.conference === 'East' ? 'Este' : t.conference === 'West' ? 'Oeste' : null

  return (
    <div className="space-y-6">
      {/* --- Cabecera --- */}
      <section
        className="rounded-xl p-5"
        style={{ background: 'var(--surface-1)', border: '1px solid var(--border)' }}
      >
        <div className="flex flex-wrap items-start gap-5">
          <TeamLogo teamId={t.team_id} name={t.full_name} size={84} />

          <div className="min-w-56 flex-1">
            <h1 className="text-2xl font-semibold leading-tight tracking-tight">
              {t.full_name}
            </h1>
            <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
              {[conf && `Conferencia ${conf}`, t.division].filter(Boolean).join(' · ')}
            </p>
            {t.wins !== null && (
              <p className="mt-2 text-lg font-semibold">
                {t.wins}-{t.losses}
                {t.playoff_rank && (
                  <span className="ml-2 text-sm font-normal" style={{ color: 'var(--text-secondary)' }}>
                    {t.playoff_rank}º del {conf}
                  </span>
                )}
              </p>
            )}
          </div>

          <dl className="grid shrink-0 grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3">
            <Dato etiqueta="Estadio" valor={t.arena} />
            <Dato
              etiqueta="Capacidad"
              valor={t.arena_capacity ? t.arena_capacity.toLocaleString('es-ES') : null}
            />
            <Dato etiqueta="Entrenador" valor={t.head_coach} />
            <Dato etiqueta="Director general" valor={t.general_manager} />
            <Dato etiqueta="Fundado" valor={t.year_founded ? String(t.year_founded) : null} />
            <Dato etiqueta="Propietario" valor={t.owner} />
          </dl>
        </div>
      </section>

      <Select
        label="Temporada"
        value={season}
        onChange={setSeason}
        options={TEMPORADAS.map((x) => ({ value: x, label: x }))}
      />

      {/* --- Récords desglosados --- */}
      {t.wins !== null && (
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ['Casa', t.home_record],
            ['Fuera', t.road_record],
            ['Conferencia', t.conference_record],
            ['División', t.division_record],
            ['Últimos 10', t.last_10],
            ['Diferencial', fmtSigned(t.diff_points_pg, 1)],
          ].map(([etiqueta, valor]) => (
            <div
              key={etiqueta as string}
              className="rounded-lg px-3.5 py-3 text-center"
              style={{ background: 'var(--surface-1)', border: '1px solid var(--border)' }}
            >
              <div className="text-[11px] uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>
                {etiqueta}
              </div>
              <div className="mt-1 text-lg font-semibold">{valor ?? '—'}</div>
            </div>
          ))}
        </div>
      )}

      {/* --- Plantilla --- */}
      <Card title={`Plantilla ${season}`} subtitle={`${t.roster.length} jugadores, por minutos`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
                <th className="py-2 pr-3 font-medium">Jugador</th>
                <th className="py-2 pr-3 font-medium">Pos</th>
                <th className="py-2 pr-3 text-right font-medium">Edad</th>
                <th className="py-2 pr-3 text-right font-medium">PJ</th>
                <th className="py-2 pr-3 text-right font-medium">Min</th>
                <th className="py-2 pr-3 text-right font-medium">PTS</th>
                <th className="py-2 pr-3 text-right font-medium">REB</th>
                <th className="py-2 text-right font-medium">AST</th>
              </tr>
            </thead>
            <tbody>
              {t.roster.map((p) => (
                <tr key={p.player_id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td className="py-2 pr-3">
                    <Link
                      to={`/jugador/${p.player_id}`}
                      className="inline-flex items-center gap-2.5 hover:underline"
                      style={{ color: 'var(--series-1)' }}
                    >
                      <PlayerPhoto playerId={p.player_id} name={p.full_name} size={32} />
                      <span className="whitespace-nowrap">
                        {p.full_name}
                        {p.jersey_number && (
                          <span className="ml-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
                            #{p.jersey_number}
                          </span>
                        )}
                      </span>
                    </Link>
                  </td>
                  <td className="py-2 pr-3" style={{ color: 'var(--text-secondary)' }}>
                    {p.position}
                  </td>
                  <td className="tabular py-2 pr-3 text-right">{fmt(p.age, 0)}</td>
                  <td className="tabular py-2 pr-3 text-right">{p.games}</td>
                  <td className="tabular py-2 pr-3 text-right">{fmt(p.min_per_game, 1)}</td>
                  <td className="tabular py-2 pr-3 text-right font-medium">
                    {fmt(p.pts_per_game, 1)}
                  </td>
                  <td className="tabular py-2 pr-3 text-right">{fmt(p.reb_per_game, 1)}</td>
                  <td className="tabular py-2 text-right">{fmt(p.ast_per_game, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* --- Historial de partidos --- */}
      <Card
        title={`Partidos ${season}`}
        subtitle={partidos.data ? `${partidos.data.length} partidos` : undefined}
      >
        {partidos.error ? (
          <ErrorBox error={partidos.error} />
        ) : !partidos.data ? (
          <Loading />
        ) : (
          <div className="max-h-[32rem] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0" style={{ background: 'var(--surface-1)' }}>
                <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
                  <th className="py-2 pr-3 font-medium">Fecha</th>
                  <th className="py-2 pr-3 font-medium">Rival</th>
                  <th className="py-2 pr-3 font-medium">Resultado</th>
                  <th className="py-2 pr-3 text-right font-medium">Of</th>
                  <th className="py-2 pr-3 text-right font-medium">Def</th>
                  <th className="py-2 text-right font-medium">Ritmo</th>
                </tr>
              </thead>
              <tbody>
                {partidos.data.map((g) => (
                  <tr key={g.game_id} style={{ borderTop: '1px solid var(--border)' }}>
                    <td className="whitespace-nowrap py-2 pr-3">
                      <div>{fmtDate(g.date)}</div>
                      <GameTypeBadge type={g.game_type} />
                    </td>
                    <td className="py-2 pr-3">
                      <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                        <span style={{ color: 'var(--text-muted)' }}>
                          {g.is_neutral_site ? 'en' : g.is_home ? 'vs' : '@'}
                        </span>
                        <TeamLogo teamId={g.opponent_id} name={g.opponent} size={20} />
                        <Link
                          to={`/equipo/${g.opponent_id}`}
                          className="hover:underline"
                          style={{ color: 'var(--series-1)' }}
                        >
                          {g.opponent}
                        </Link>
                      </span>
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3">
                      <WinLoss won={g.won} />{' '}
                      <span className="tabular" style={{ color: 'var(--text-secondary)' }}>
                        {g.pts}-{g.opp_pts}
                      </span>
                    </td>
                    <td className="tabular py-2 pr-3 text-right">{fmt(g.off_rating, 1)}</td>
                    <td className="tabular py-2 pr-3 text-right">{fmt(g.def_rating, 1)}</td>
                    <td className="tabular py-2 text-right" style={{ color: 'var(--text-secondary)' }}>
                      {fmt(g.pace, 1)}
                    </td>
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
