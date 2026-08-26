import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { SplitsCard, TrendCard } from '../components/AnalysisSection'
import { GameHistory } from '../components/GameHistory'
import { Card, ErrorBox, Loading, Select } from '../components/Layout'
import { PlayerPhoto, TeamLogo } from '../components/Media'
import { fmt, fmtSigned } from '../lib/format'


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
  // Ya se pedía `/catalog` para las dimensiones y se ignoraba su `seasons`.
  const catalogo = useQuery({ queryKey: ['catalog'], queryFn: api.catalog })
  const temporadas = catalogo.data?.seasons ?? []
  const [elegida, setSeason] = useState('')
  const season = elegida || temporadas[0] || ''
  const [stat, setStat] = useState('net_rating')
  const [dimension, setDimension] = useState('home_away')

  // El análisis tiene su PROPIO alcance, separado del de la plantilla y el
  // calendario, y por defecto abarca las 5 temporadas.
  //
  // El motivo salió de los datos: con una sola temporada (41 partidos en casa)
  // ni siquiera la ventaja de campo —un efecto real y bien documentado— alcanza
  // significación. OKC en 2025-26 daba 11,50 en casa y 10,79 fuera, indistinguible
  // del azar; con las cinco temporadas da 7,52 contra 1,90, y sí lo es (q=0,0007).
  // Dejar el análisis atado a una temporada habría hecho que la pantalla
  // respondiera "aquí no hay patrón" a casi todo, por falta de datos y no por
  // ausencia de efecto.
  //
  // A cambio, juntar cinco temporadas mezcla plantillas distintas. Por eso es un
  // selector y no una constante: la pregunta "¿cómo juega ESTE equipo?" y "¿cómo
  // juega esta franquicia?" no son la misma.
  const [alcance, setAlcance] = useState<'todas' | 'temporada'>('todas')
  const temporadasAnalisis = alcance === 'todas' ? undefined : [season]

  const catalogoEquipo = useQuery({
    queryKey: ['teamCatalog'],
    queryFn: api.teamCatalog,
  })

  const tendencia = useQuery({
    queryKey: ['teamTrend', teamId, stat, alcance, season],
    queryFn: () => api.teamTrend(teamId, stat, temporadasAnalisis),
    placeholderData: (prev) => prev,
  })
  const splits = useQuery({
    queryKey: ['teamSplits', teamId, dimension, stat, alcance, season],
    queryFn: () => api.teamSplits(teamId, dimension, stat, temporadasAnalisis),
    placeholderData: (prev) => prev,
  })

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
        options={temporadas.map((x) => ({ value: x, label: x }))}
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
        subtitle="Incluye playoffs, play-in y NBA Cup. Haz clic en un partido para ver todo."
      >
        {partidos.error ? (
          <ErrorBox error={partidos.error} />
        ) : !partidos.data ? (
          <Loading />
        ) : (
          <GameHistory games={partidos.data} />
        )}
      </Card>

      {/* --- Análisis del equipo --- */}
      <div className="flex flex-wrap items-center gap-4 pt-2">
        <h2 className="text-sm font-semibold">Análisis</h2>
        <Select
          label="Estadística"
          value={stat}
          onChange={setStat}
          options={(catalogoEquipo.data?.stats ?? []).map((x) => ({
            value: x.value,
            label: x.label,
          }))}
        />
        <Select
          label="Split por"
          value={dimension}
          onChange={setDimension}
          options={(catalogo.data?.dimensions ?? []).map((d) => ({
            value: d.value,
            label: d.label,
          }))}
        />
        <Select
          label="Alcance"
          value={alcance}
          onChange={(v) => setAlcance(v as 'todas' | 'temporada')}
          options={[
            { value: 'todas', label: 'Las 5 temporadas' },
            { value: 'temporada', label: `Solo ${season}` },
          ]}
        />
      </div>

      <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
        Las métricas de equipo van normalizadas por <strong>100 posesiones</strong>,
        no por minutos: un equipo siempre juega 48, así que lo que distingue a uno
        de otro no son los minutos sino cuántas posesiones caben dentro. Comparar
        puntos por partido entre épocas mezcla «anota mejor» con «juega más rápido».
        {alcance === 'temporada' && (
          <>
            {' '}Con una sola temporada hay ~41 partidos por split: ni siquiera la
            ventaja de campo alcanza significación con esa muestra. Si todo sale como
            «sin patrón», prueba con las 5 temporadas.
          </>
        )}
      </p>

      <TrendCard
        trend={tendencia.data}
        error={tendencia.error}
        titulo={alcance === 'todas' ? 'Trayectoria' : `Trayectoria en ${season}`}
      />
      <SplitsCard splits={splits.data} error={splits.error} />
    </div>
  )
}
