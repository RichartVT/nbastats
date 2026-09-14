import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ScheduledGame } from '../api/types'
import { fmtGameDay, fmtTime } from '../lib/format'
import { GameTypeBadge, TeamLogo, WinLoss } from './Media'

/**
 * Calendario de un equipo: qué partidos vienen y cuándo.
 *
 * Es lo único que tiene algo que enseñar antes de que empiece la temporada,
 * cuando el historial está vacío. Por eso NO es el historial con otro orden:
 * las columnas que importan aquí son la fecha, la hora y dónde se juega, no
 * el rating ofensivo.
 *
 * La lista arranca en el próximo partido, no en el primero de la temporada.
 * En marzo, «qué viene ahora» está a mitad de una tabla de 82 filas, y hacer
 * bajar hasta ahí cada vez sería una forma tonta de gastar el scroll del que
 * mira. Los ya jugados siguen ahí, a un clic.
 */

type Vista = 'proximos' | 'todos'

export function TeamSchedule({ games }: { games: ScheduledGame[] }) {
  const jugados = games.filter((g) => g.played).length
  const pendientes = games.length - jugados

  // LA VISTA SE DERIVA, NO SE GUARDA COMO ESTADO INICIAL. `useState` solo
  // evalúa su inicializador la primera vez, y este componente no se desmonta al
  // cambiar de temporada en el selector de arriba: se le pasan otros partidos.
  // Guardar «próximos» al entrar en 2026-27 dejaba el calendario en blanco en
  // cuanto se elegía una temporada ya terminada, que no tiene ninguno.
  //
  // Lo que sí se guarda es la elección EXPLÍCITA, y aun esa cae a «todos»
  // cuando no queda nada por jugar: una preferencia no debe poder vaciar la
  // tabla.
  const [elegida, setVista] = useState<Vista | null>(null)
  const vista: Vista =
    pendientes === 0 ? 'todos' : (elegida ?? 'proximos')

  const visibles = useMemo(
    () => (vista === 'proximos' ? games.filter((g) => !g.played) : games),
    [games, vista],
  )

  if (games.length === 0) {
    return (
      <p className="py-6 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
        La NBA todavía no ha publicado el calendario de esta temporada.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1.5">
          {([
            ['proximos', `Por jugar (${pendientes})`],
            ['todos', `Toda la temporada (${games.length})`],
          ] as const).map(([valor, etiqueta]) => (
            <button
              key={valor}
              onClick={() => setVista(valor)}
              disabled={valor === 'proximos' && pendientes === 0}
              className="rounded-md px-2.5 py-1.5 text-xs disabled:opacity-40"
              style={{
                background: vista === valor ? 'var(--surface-2)' : 'var(--surface-page)',
                color: vista === valor ? 'var(--text-primary)' : 'var(--text-secondary)',
                border: `1px solid ${vista === valor ? 'var(--series-1)' : 'var(--border)'}`,
              }}
            >
              {etiqueta}
            </button>
          ))}
        </div>
        {jugados > 0 && (
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {jugados} jugados
          </span>
        )}
      </div>

      {visibles.length === 0 ? (
        <p className="py-6 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
          No queda ningún partido por jugar.
        </p>
      ) : (
        <div className="max-h-[34rem] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10" style={{ background: 'var(--surface-1)' }}>
              <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
                <th className="py-2 pr-3 font-medium">Fecha</th>
                <th className="py-2 pr-3 font-medium">Hora</th>
                <th className="py-2 pr-3 font-medium">Rival</th>
                <th className="py-2 pr-3 font-medium">Dónde</th>
                <th className="py-2 text-right font-medium">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {visibles.map((g) => (
                <tr
                  key={g.game_id}
                  style={{ borderTop: '1px solid var(--border)' }}
                  className="hover:bg-[color:var(--surface-page)]"
                >
                  <td className="whitespace-nowrap py-2 pr-3">
                    {fmtGameDay(g.date, g.tipoff_utc)}
                    <div>
                      <GameTypeBadge type={g.game_type} />
                    </div>
                  </td>
                  <td
                    className="tabular whitespace-nowrap py-2 pr-3"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {fmtTime(g.tipoff_utc)}
                  </td>
                  <td className="py-2 pr-3">
                    {g.opponent_id === null ? (
                      // Los cruces de la Copa se publican sin contendientes y
                      // se rellenan en diciembre. Decirlo es más útil que
                      // esconder la fecha.
                      <span style={{ color: 'var(--text-muted)' }}>Por determinar</span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                        <span style={{ color: 'var(--text-muted)' }}>
                          {g.is_neutral_site ? 'en' : g.is_home ? 'vs' : '@'}
                        </span>
                        <TeamLogo teamId={g.opponent_id} name={g.opponent ?? ''} size={20} />
                        <Link
                          to={`/equipo/${g.opponent_id}`}
                          className="hover:underline"
                          style={{ color: 'var(--series-1)' }}
                        >
                          {g.opponent}
                        </Link>
                      </span>
                    )}
                  </td>
                  <td
                    className="whitespace-nowrap py-2 pr-3 text-xs"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {g.arena_name ?? '—'}
                    {g.is_neutral_site && g.arena_city && (
                      <span style={{ color: 'var(--series-3)' }}> · {g.arena_city}</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap py-2 text-right">
                    {g.played ? (
                      <Link to={`/partido/${g.game_id}`} className="hover:underline">
                        <WinLoss won={g.pts !== null && g.opp_pts !== null
                          ? g.pts > g.opp_pts
                          : null} />{' '}
                        <span className="tabular" style={{ color: 'var(--text-secondary)' }}>
                          {g.pts}-{g.opp_pts}
                        </span>
                      </Link>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    )}
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
