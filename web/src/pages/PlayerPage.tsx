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

  // Por cuarto no hay tasas: extrapolar a 36 minutos desde los 4 que alguien
  // jugó en un tercer cuarto da un número sin sentido, y la API lo rechaza. Se
  // filtra el menú en vez de dejar elegir algo que va a fallar, y si ya había
  // una tasa seleccionada al cambiar de dimensión se cae a puntos, en lugar de
  // dejar la pantalla en error hasta que el usuario adivine por qué.
  const esPorCuarto = dimension === 'period'
  const statsDisponibles = (catalogo.data?.stats ?? []).filter(
    (s) => !esPorCuarto || !s.is_rate,
  )
  const statEfectivo =
    esPorCuarto && !statsDisponibles.some((s) => s.value === stat) ? 'pts' : stat
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
    queryKey: ['splits', playerId, dimension, statEfectivo],
    queryFn: () => api.splits(playerId, dimension, statEfectivo),
    placeholderData: (prev) => prev,
  })

  if (jugador.error) return <ErrorBox error={jugador.error} />
  if (!jugador.data) return <Loading />

  const opcionesStat = statsDisponibles.map((s) => ({ value: s.value, label: s.label }))
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
                  {/* Titularidades. Se carga desde la fase 24; en temporadas
                      sin el dato se enseña un guion en vez de un cero, que
                      diría algo falso. */}
                  <th
                    className="py-2 pr-3 text-right font-medium"
                    title="Partidos como titular"
                  >
                    TIT
                  </th>
                  <th className="py-2 pr-3 text-right font-medium">Min</th>
                  <th className="py-2 pr-3 text-right font-medium">PTS</th>
                  <th className="py-2 pr-3 text-right font-medium">REB</th>
                  <th className="py-2 pr-3 text-right font-medium">AST</th>
                  <th className="py-2 pr-3 text-right font-medium">ROB</th>
                  <th className="py-2 pr-3 text-right font-medium">TAP</th>
                  <th className="py-2 pr-3 text-right font-medium">PER</th>
                  <th className="py-2 pr-3 text-right font-medium">TC%</th>
                  {/* Los triples con volumen Y porcentaje: un 45% con 2
                      intentos por partido y un 38% con 10 no son la misma
                      habilidad, y el porcentaje solo no lo distingue. */}
                  <th className="py-2 pr-3 text-right font-medium">3P</th>
                  <th className="py-2 pr-3 text-right font-medium">3P%</th>
                  <th className="py-2 pr-3 text-right font-medium">TL%</th>
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
                    <td
                      className="tabular py-2 pr-3 text-right"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {t.games_started ?? '—'}
                    </td>
                    <td className="tabular py-2 pr-3 text-right">{fmt(t.min_per_game, 1)}</td>
                    <td className="tabular py-2 pr-3 text-right font-medium">
                      {fmt(t.pts_per_game, 1)}
                    </td>
                    <td className="tabular py-2 pr-3 text-right">{fmt(t.reb_per_game, 1)}</td>
                    <td className="tabular py-2 pr-3 text-right">{fmt(t.ast_per_game, 1)}</td>
                    <td className="tabular py-2 pr-3 text-right">
                      {fmt((t.stl ?? 0) / (t.games_played || 1), 1)}
                    </td>
                    <td className="tabular py-2 pr-3 text-right">
                      {fmt((t.blk ?? 0) / (t.games_played || 1), 1)}
                    </td>
                    <td className="tabular py-2 pr-3 text-right">
                      {fmt((t.tov ?? 0) / (t.games_played || 1), 1)}
                    </td>
                    <td className="tabular py-2 pr-3 text-right">{fmtPct(t.fg_pct)}</td>
                    <td
                      className="tabular py-2 pr-3 text-right whitespace-nowrap"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {fmt(t.fg3m_per_game, 1)}/{fmt(t.fg3a_per_game, 1)}
                    </td>
                    <td className="tabular py-2 pr-3 text-right font-medium">
                      {fmtPct(t.fg3_pct)}
                    </td>
                    <td className="tabular py-2 pr-3 text-right">{fmtPct(t.ft_pct)}</td>
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
        <Select
          label="Estadística"
          value={statEfectivo}
          onChange={setStat}
          options={opcionesStat}
        />
        <Select label="Split por" value={dimension} onChange={setDimension} options={opcionesDim} />
      </div>

      <TrendCard trend={tendencia.data} error={tendencia.error} />
      <SplitsCard splits={splits.data} error={splits.error} />
    </div>
  )
}
