import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { TeamGame } from '../api/types'
import { fmt, fmtDate, fmtSigned } from '../lib/format'
import { GameTypeBadge, TeamLogo, WinLoss } from './Media'

/**
 * Historial de partidos con filtros.
 *
 * El filtrado ocurre en el NAVEGADOR, no en el servidor. Una temporada son ~90
 * partidos: caben de sobra en memoria y filtrarlos es instantáneo, mientras que
 * hacerlo en el servidor significaría un viaje de red por cada clic en un
 * desplegable. El endpoint sigue aceptando filtros para quien consuma la API
 * directamente; esta pantalla simplemente no los necesita.
 */

type Localia = 'todos' | 'local' | 'visitante'
type Resultado = 'todos' | 'ganados' | 'perdidos'
type Descanso = 'todos' | 'b2b' | 'descansado'

const ORDENES = {
  fecha_desc: 'Más recientes',
  fecha_asc: 'Más antiguos',
  dif_desc: 'Mayor victoria',
  dif_asc: 'Mayor derrota',
  pts_desc: 'Más anotados',
} as const

type Orden = keyof typeof ORDENES

function Filtro<T extends string>({
  etiqueta,
  valor,
  onChange,
  opciones,
}: {
  etiqueta: string
  valor: T
  onChange: (v: T) => void
  opciones: { value: T; label: string }[]
}) {
  return (
    <label
      className="flex items-center gap-2 text-xs"
      style={{ color: 'var(--text-secondary)' }}
    >
      {etiqueta}
      <select
        value={valor}
        onChange={(e) => onChange(e.target.value as T)}
        className="rounded-md px-2.5 py-1.5 text-xs"
        style={{
          background: 'var(--surface-1)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border)',
        }}
      >
        {opciones.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function GameHistory({ games }: { games: TeamGame[] }) {
  const [localia, setLocalia] = useState<Localia>('todos')
  const [resultado, setResultado] = useState<Resultado>('todos')
  const [tipo, setTipo] = useState('todos')
  const [rival, setRival] = useState('todos')
  const [descanso, setDescanso] = useState<Descanso>('todos')
  const [orden, setOrden] = useState<Orden>('fecha_desc')

  // Las opciones salen de los partidos que hay, no de una lista fija: si un
  // equipo no jugó playoffs, la opción no aparece en vez de dar cero resultados.
  const tiposPresentes = useMemo(() => {
    const vistos = new Map<string, string>()
    for (const g of games) vistos.set(g.game_type.key, g.game_type.label)
    return [...vistos.entries()].map(([value, label]) => ({ value, label }))
  }, [games])

  const rivalesPresentes = useMemo(() => {
    const vistos = new Map<string, string>()
    for (const g of games) vistos.set(g.opponent, g.opponent)
    return [...vistos.keys()].sort().map((v) => ({ value: v, label: v }))
  }, [games])

  const filtrados = useMemo(() => {
    const out = games.filter((g) => {
      if (localia === 'local' && !g.is_home) return false
      if (localia === 'visitante' && g.is_home) return false
      if (resultado === 'ganados' && !g.won) return false
      if (resultado === 'perdidos' && g.won !== false) return false
      if (tipo !== 'todos' && g.game_type.key !== tipo) return false
      if (rival !== 'todos' && g.opponent !== rival) return false
      if (descanso === 'b2b' && !g.is_back_to_back) return false
      if (descanso === 'descansado' && g.is_back_to_back !== false) return false
      return true
    })

    const cmp: Record<Orden, (a: TeamGame, b: TeamGame) => number> = {
      fecha_desc: (a, b) => b.date.localeCompare(a.date),
      fecha_asc: (a, b) => a.date.localeCompare(b.date),
      dif_desc: (a, b) => (b.point_diff ?? 0) - (a.point_diff ?? 0),
      dif_asc: (a, b) => (a.point_diff ?? 0) - (b.point_diff ?? 0),
      pts_desc: (a, b) => (b.pts ?? 0) - (a.pts ?? 0),
    }
    return [...out].sort(cmp[orden])
  }, [games, localia, resultado, tipo, rival, descanso, orden])

  const ganados = filtrados.filter((g) => g.won).length
  const perdidos = filtrados.filter((g) => g.won === false).length
  const difMedia = filtrados.length
    ? filtrados.reduce((a, g) => a + (g.point_diff ?? 0), 0) / filtrados.length
    : null

  const hayFiltro =
    localia !== 'todos' ||
    resultado !== 'todos' ||
    tipo !== 'todos' ||
    rival !== 'todos' ||
    descanso !== 'todos'

  return (
    <div className="space-y-3">
      {/* Una sola fila de filtros por encima de todo lo que afectan. */}
      <div className="flex flex-wrap items-center gap-3">
        <Filtro
          etiqueta="Dónde"
          valor={localia}
          onChange={setLocalia}
          opciones={[
            { value: 'todos', label: 'Todos' },
            { value: 'local', label: 'Local' },
            { value: 'visitante', label: 'Visitante' },
          ]}
        />
        <Filtro
          etiqueta="Resultado"
          valor={resultado}
          onChange={setResultado}
          opciones={[
            { value: 'todos', label: 'Todos' },
            { value: 'ganados', label: 'Ganados' },
            { value: 'perdidos', label: 'Perdidos' },
          ]}
        />
        <Filtro
          etiqueta="Tipo"
          valor={tipo}
          onChange={setTipo}
          opciones={[{ value: 'todos', label: 'Todos' }, ...tiposPresentes]}
        />
        <Filtro
          etiqueta="Rival"
          valor={rival}
          onChange={setRival}
          opciones={[{ value: 'todos', label: 'Todos' }, ...rivalesPresentes]}
        />
        <Filtro
          etiqueta="Descanso"
          valor={descanso}
          onChange={setDescanso}
          opciones={[
            { value: 'todos', label: 'Todos' },
            { value: 'b2b', label: '2º en 2 días' },
            { value: 'descansado', label: 'Con descanso' },
          ]}
        />
        <Filtro
          etiqueta="Orden"
          valor={orden}
          onChange={setOrden}
          opciones={Object.entries(ORDENES).map(([value, label]) => ({
            value: value as Orden,
            label,
          }))}
        />
        {hayFiltro && (
          <button
            onClick={() => {
              setLocalia('todos')
              setResultado('todos')
              setTipo('todos')
              setRival('todos')
              setDescanso('todos')
            }}
            className="rounded-md px-2.5 py-1.5 text-xs"
            style={{
              background: 'var(--surface-page)',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border)',
            }}
          >
            Limpiar
          </button>
        )}
      </div>

      {/* Resumen de lo que queda tras filtrar. Con un filtro puesto, el récord
          del subconjunto es justo lo que se quería saber. */}
      <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
        <strong style={{ color: 'var(--text-primary)' }}>
          {filtrados.length} partidos
        </strong>
        {filtrados.length > 0 && (
          <>
            {' · '}
            {ganados}-{perdidos}
            {difMedia !== null && ` · diferencial medio ${fmtSigned(difMedia, 1)}`}
          </>
        )}
      </p>

      {filtrados.length === 0 ? (
        <p className="py-6 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
          Ningún partido cumple estos filtros.
        </p>
      ) : (
        <div className="max-h-[34rem] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10" style={{ background: 'var(--surface-1)' }}>
              <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
                <th className="py-2 pr-3 font-medium">Fecha</th>
                <th className="py-2 pr-3 font-medium">Rival</th>
                <th className="py-2 pr-3 font-medium">Resultado</th>
                <th className="py-2 pr-3 text-right font-medium">Dif</th>
                <th className="py-2 pr-3 text-right font-medium">Of</th>
                <th className="py-2 pr-3 text-right font-medium">Def</th>
                <th className="py-2 pr-3 text-right font-medium">Ritmo</th>
                <th className="py-2 text-right font-medium">TS%</th>
              </tr>
            </thead>
            <tbody>
              {filtrados.map((g) => (
                <tr
                  key={g.game_id}
                  style={{ borderTop: '1px solid var(--border)' }}
                  className="hover:bg-[color:var(--surface-page)]"
                >
                  <td className="whitespace-nowrap py-2 pr-3">
                    <Link
                      to={`/partido/${g.game_id}`}
                      className="hover:underline"
                      style={{ color: 'var(--series-1)' }}
                    >
                      {fmtDate(g.date)}
                    </Link>
                    <div>
                      <GameTypeBadge type={g.game_type} />
                    </div>
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
                    <Link to={`/partido/${g.game_id}`} className="hover:underline">
                      <WinLoss won={g.won} />{' '}
                      <span className="tabular" style={{ color: 'var(--text-secondary)' }}>
                        {g.pts}-{g.opp_pts}
                      </span>
                    </Link>
                  </td>
                  <td
                    className="tabular py-2 pr-3 text-right"
                    style={{
                      color:
                        (g.point_diff ?? 0) > 0
                          ? 'var(--status-good)'
                          : 'var(--status-critical)',
                    }}
                  >
                    {fmtSigned(g.point_diff, 0)}
                  </td>
                  <td className="tabular py-2 pr-3 text-right">{fmt(g.off_rating, 1)}</td>
                  <td className="tabular py-2 pr-3 text-right">{fmt(g.def_rating, 1)}</td>
                  <td
                    className="tabular py-2 pr-3 text-right"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {fmt(g.pace, 1)}
                  </td>
                  <td className="tabular py-2 text-right">
                    {g.ts_pct === null ? '—' : `${(g.ts_pct * 100).toFixed(1)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
