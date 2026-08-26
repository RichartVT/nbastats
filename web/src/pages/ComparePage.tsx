import { useQueries, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Trend } from '../api/types'
import {
  ComparisonChart,
  MAX_JUGADORES,
} from '../components/ComparisonChart'
import { COLORES_SERIE } from '../lib/colors'
import { Card, ErrorBox, Loading, Select } from '../components/Layout'
import { PlayerPhoto } from '../components/Media'
import { ReliabilityBadge } from '../components/Reliability'
import { fmtSigned, fmtStat } from '../lib/format'

const DIRECCION: Record<string, { texto: string; color: string; icono: string }> = {
  alza: { texto: 'Al alza', color: 'var(--status-good)', icono: '▲' },
  declive: { texto: 'En declive', color: 'var(--status-critical)', icono: '▼' },
  estable: { texto: 'Estable', color: 'var(--text-secondary)', icono: '=' },
  indeterminada: { texto: 'Sin datos', color: 'var(--text-muted)', icono: '·' },
}

/**
 * Comparador de jugadores.
 *
 * Los ids viajan en la URL (`?p=2544&p=1629029`) para que una comparación
 * concreta se pueda guardar o compartir. Es barato de implementar y convierte
 * la pantalla en algo enlazable en vez de un estado efímero.
 */
export function ComparePage() {
  const [params, setParams] = useSearchParams()
  const [stat, setStat] = useState('pts_per_36')
  const [busqueda, setBusqueda] = useState('')

  const ids = params
    .getAll('p')
    .map(Number)
    .filter((n) => Number.isFinite(n))
    .slice(0, MAX_JUGADORES)

  const setIds = (nuevos: number[]) => {
    const p = new URLSearchParams()
    nuevos.forEach((id) => p.append('p', String(id)))
    setParams(p, { replace: true })
  }

  const catalogo = useQuery({ queryKey: ['catalog'], queryFn: api.catalog })
  const resultados = useQuery({
    queryKey: ['players', busqueda],
    queryFn: () => api.searchPlayers(busqueda, 8),
    enabled: busqueda.length >= 2,
  })

  // Una consulta por jugador: el backend ya devuelve la serie completa y la
  // media móvil, así que no hace falta un endpoint de comparación aparte.
  const tendencias = useQueries({
    queries: ids.map((id) => ({
      queryKey: ['trend', id, stat],
      queryFn: () => api.trend(id, stat),
      placeholderData: (prev: Trend | undefined) => prev,
    })),
  })

  const cargando = tendencias.some((t) => t.isLoading && !t.data)
  const error = tendencias.find((t) => t.error)?.error
  const datos = tendencias.map((t) => t.data).filter((t): t is Trend => Boolean(t))

  const opcionesStat = (catalogo.data?.stats ?? [])
    // Solo tasas: comparar totales por partido entre jugadores confunde "rinde
    // mejor" con "juega más minutos", que es lo primero que hay que separar.
    .filter((s) => s.is_rate)
    .map((s) => ({ value: s.value, label: s.label }))

  const lleno = ids.length >= MAX_JUGADORES

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Comparar jugadores</h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
          Hasta {MAX_JUGADORES} jugadores superpuestos, en tasas normalizadas por
          minutos.
        </p>
      </div>

      {/* --- Selección --- */}
      <Card title="Jugadores">
        <div className="space-y-4">
          {ids.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {ids.map((id, i) => {
                const t = tendencias[i]?.data
                return (
                  <span
                    key={id}
                    className="inline-flex items-center gap-2 rounded-full py-1 pl-1 pr-2.5 text-sm"
                    style={{
                      background: 'var(--surface-page)',
                      border: `1px solid ${COLORES_SERIE[i]}`,
                    }}
                  >
                    <PlayerPhoto playerId={id} name={t?.player_name ?? '?'} size={24} />
                    <span>{t?.player_name ?? `#${id}`}</span>
                    <button
                      onClick={() => setIds(ids.filter((x) => x !== id))}
                      aria-label={`Quitar a ${t?.player_name ?? id}`}
                      className="ml-0.5 leading-none"
                      style={{ color: 'var(--text-muted)' }}
                    >
                      ✕
                    </button>
                  </span>
                )
              })}
            </div>
          )}

          <div>
            <input
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              placeholder={
                lleno
                  ? `Máximo ${MAX_JUGADORES}: quita uno para añadir otro`
                  : 'Buscar y añadir jugador…'
              }
              disabled={lleno}
              className="w-full max-w-md rounded-lg px-3.5 py-2.5 text-sm outline-none disabled:opacity-50"
              style={{
                background: 'var(--surface-1)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border)',
              }}
            />

            {!lleno && busqueda.length >= 2 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {(resultados.data ?? [])
                  .filter((p) => !ids.includes(p.player_id))
                  .map((p) => (
                    <button
                      key={p.player_id}
                      onClick={() => {
                        setIds([...ids, p.player_id])
                        setBusqueda('')
                      }}
                      className="inline-flex items-center gap-2 rounded-full py-1 pl-1 pr-3 text-sm"
                      style={{
                        background: 'var(--surface-page)',
                        border: '1px solid var(--border)',
                        color: 'var(--text-primary)',
                      }}
                    >
                      <PlayerPhoto playerId={p.player_id} name={p.full_name} size={24} />
                      {p.full_name}
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                        +
                      </span>
                    </button>
                  ))}
                {resultados.data?.length === 0 && (
                  <span className="text-sm" style={{ color: 'var(--text-muted)' }}>
                    Sin resultados.
                  </span>
                )}
              </div>
            )}
          </div>

          {ids.length > 0 && (
            <Select
              label="Estadística"
              value={stat}
              onChange={setStat}
              options={opcionesStat}
            />
          )}
        </div>
      </Card>

      {ids.length === 0 ? null : error ? (
        <ErrorBox error={error} />
      ) : cargando ? (
        <Loading />
      ) : (
        <>
          <Card title="Evolución" subtitle={datos[0]?.stat_label}>
            <ComparisonChart trends={datos} />
          </Card>

          <Card title="Resumen" subtitle="Sobre las 5 temporadas cargadas">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
                    <th className="py-2 pr-4 font-medium">Jugador</th>
                    <th className="py-2 pr-4 text-right font-medium">Media</th>
                    <th className="py-2 pr-4 text-right font-medium">Últimos 25</th>
                    <th className="py-2 pr-4 font-medium">Tendencia</th>
                    <th className="py-2 pr-4 text-right font-medium">Por temporada</th>
                    <th className="py-2 font-medium">Muestra</th>
                  </tr>
                </thead>
                <tbody>
                  {datos.map((t, i) => {
                    const media =
                      t.series.reduce((a, b) => a + b, 0) / (t.series.length || 1)
                    const recientes = t.series.slice(-25)
                    const ultimos =
                      recientes.reduce((a, b) => a + b, 0) / (recientes.length || 1)
                    const d = DIRECCION[t.direction]
                    return (
                      <tr
                        key={t.player_id}
                        style={{ borderTop: '1px solid var(--border)' }}
                      >
                        <td className="py-2 pr-4">
                          <Link
                            to={`/jugador/${t.player_id}`}
                            className="inline-flex items-center gap-2 hover:underline"
                            style={{ color: 'var(--series-1)' }}
                          >
                            <span aria-hidden style={{ color: COLORES_SERIE[i] }}>▬</span>
                            {t.player_name}
                          </Link>
                        </td>
                        <td className="tabular py-2 pr-4 text-right font-medium">
                          {fmtStat(media, t.stat)}
                        </td>
                        <td className="tabular py-2 pr-4 text-right">
                          {fmtStat(ultimos, t.stat)}
                        </td>
                        <td className="py-2 pr-4">
                          <span
                            className="inline-flex items-center gap-1.5"
                            style={{ color: d.color }}
                          >
                            <span aria-hidden>{d.icono}</span>
                            {d.texto}
                          </span>
                        </td>
                        <td
                          className="tabular py-2 pr-4 text-right"
                          style={{ color: 'var(--text-secondary)' }}
                        >
                          {t.direction === 'estable' || t.direction === 'indeterminada'
                            ? '—'
                            : fmtSigned(t.slope_per_season)}
                        </td>
                        <td className="py-2">
                          <ReliabilityBadge reliability={t.reliability} n={t.n} />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
              La columna «Por temporada» solo trae número cuando los dos tests
              —Mann-Kendall y el intervalo de la pendiente— coinciden en que hay
              tendencia. Un guion significa que la trayectoria no se distingue de
              una línea plana, no que valga cero.
            </p>
          </Card>
        </>
      )}
    </div>
  )
}
