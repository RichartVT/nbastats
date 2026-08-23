import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import { SplitsCard, TrendCard } from '../components/AnalysisSection'
import { Card, ErrorBox, Loading, Select } from '../components/Layout'
import { PlayerHeader, SeasonTiles } from '../components/PlayerHeader'
import { RecentGames } from '../components/RecentGames'
import { fmt, fmtPct } from '../lib/format'

/**
 * Ficha de jugador.
 *
 * El orden de las secciones importa y no es casual: identidad, rendimiento
 * reciente, trayectoria y — solo al final — splits condicionales. Los splits
 * son una función más, no el esqueleto de la aplicación: la mayoría de las
 * veces su respuesta honesta es "aquí no hay patrón", y esa no es la primera
 * información que alguien quiere de un jugador.
 */
export function PlayerPage() {
  const { id } = useParams()
  const playerId = Number(id)

  const [stat, setStat] = useState('pts_per_36')
  const [dimension, setDimension] = useState('home_away')

  const catalogo = useQuery({ queryKey: ['catalog'], queryFn: api.catalog })
  const jugador = useQuery({
    queryKey: ['player', playerId],
    queryFn: () => api.player(playerId),
  })
  const temporadas = useQuery({
    queryKey: ['seasons', playerId],
    queryFn: () => api.seasons(playerId),
  })
  const recientes = useQuery({
    queryKey: ['recent', playerId],
    queryFn: () => api.recent(playerId, 5),
  })

  // La temporada más reciente que jugó. Los puestos de liga solo tienen
  // sentido dentro de una temporada concreta.
  const ultimaTemporada = jugador.data?.seasons?.at(-1)
  const ranks = useQuery({
    queryKey: ['ranks', playerId, ultimaTemporada],
    queryFn: () => api.ranks(playerId, ultimaTemporada as string),
    enabled: Boolean(ultimaTemporada),
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

  const opcionesStat = (catalogo.data?.stats ?? []).map((s) => ({
    value: s.value,
    label: s.label,
  }))
  const opcionesDim = (catalogo.data?.dimensions ?? []).map((d) => ({
    value: d.value,
    label: d.label,
  }))
  const regulares = (temporadas.data ?? []).filter((t) => t.season_type === 'regular')

  return (
    <div className="space-y-6">
      {/* 1. Identidad */}
      <PlayerHeader p={jugador.data} />

      {/* 2. Rendimiento de la última temporada, con su puesto en la liga */}
      {ranks.data && (
        <Card
          title={`Temporada regular ${ranks.data.season_id}`}
          subtitle="Promedios y puesto en la liga"
        >
          <SeasonTiles ranks={ranks.data} />
        </Card>
      )}
      {ultimaTemporada && ranks.isFetched && !ranks.data && (
        <Card title={`Temporada regular ${ultimaTemporada}`}>
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            No alcanza el mínimo de 58 partidos que exige la NBA para entrar en el
            ranking de la liga. Compararlo con los titulares no daría un número
            interpretable.
          </p>
        </Card>
      )}

      {/* 3. Últimos partidos */}
      <Card title="Últimos partidos">
        {recientes.error ? (
          <ErrorBox error={recientes.error} />
        ) : !recientes.data ? (
          <Loading />
        ) : (
          <RecentGames games={recientes.data} />
        )}
      </Card>

      {/* 4. Por temporada */}
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

      {/* --- A partir de aquí, análisis --- */}
      <div className="flex flex-wrap items-center gap-4 pt-2">
        <h2 className="text-sm font-semibold">Análisis</h2>
        <Select label="Estadística" value={stat} onChange={setStat} options={opcionesStat} />
        <Select label="Split por" value={dimension} onChange={setDimension} options={opcionesDim} />
      </div>

      <TrendCard trend={tendencia.data} error={tendencia.error} />
      <SplitsCard splits={splits.data} error={splits.error} />
    </div>
  )
}
