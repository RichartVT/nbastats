import { Link } from 'react-router-dom'
import type { RecentGame } from '../api/types'
import { fmt, fmtDate } from '../lib/format'
import { GameTypeBadge, TeamLogo, WinLoss } from './Media'

export function RecentGames({ games }: { games: RecentGame[] }) {
  if (games.length === 0) {
    return <p style={{ color: 'var(--text-muted)' }}>Sin partidos registrados.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
            <th className="py-2 pr-3 font-medium">Fecha</th>
            <th className="py-2 pr-3 font-medium">Rival</th>
            <th className="py-2 pr-3 font-medium">Resultado</th>
            <th className="py-2 pr-3 text-right font-medium">Min</th>
            <th className="py-2 pr-3 text-right font-medium">PTS</th>
            <th className="py-2 pr-3 text-right font-medium">REB</th>
            <th className="py-2 pr-3 text-right font-medium">AST</th>
            <th className="py-2 pr-3 text-right font-medium">TC</th>
            <th className="py-2 pr-3 text-right font-medium">3P</th>
            <th className="py-2 pr-3 text-right font-medium">+/-</th>
          </tr>
        </thead>
        <tbody>
          {games.map((g) => (
            <tr key={g.game_id} style={{ borderTop: '1px solid var(--border)' }}>
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
                    {g.team_pts}-{g.opp_pts}
                  </span>
                </Link>
              </td>
              <td className="tabular py-2 pr-3 text-right">{g.minutes}</td>
              <td className="tabular py-2 pr-3 text-right font-medium">{g.pts}</td>
              <td className="tabular py-2 pr-3 text-right">{g.reb}</td>
              <td className="tabular py-2 pr-3 text-right">{g.ast}</td>
              <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--text-secondary)' }}>
                {g.fgm}/{g.fga}
              </td>
              {/* Anotados/intentados, no el porcentaje: con 5 intentos un
                  porcentaje es ruido, y el volumen es dato por sí mismo. */}
              <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--text-secondary)' }}>
                {g.fg3m ?? '—'}/{g.fg3a ?? '—'}
              </td>
              <td
                className="tabular py-2 pr-3 text-right"
                style={{
                  color:
                    (g.plus_minus ?? 0) > 0
                      ? 'var(--status-good)'
                      : (g.plus_minus ?? 0) < 0
                        ? 'var(--status-critical)'
                        : 'var(--text-secondary)',
                }}
              >
                {g.plus_minus === null ? '—' : `${g.plus_minus > 0 ? '+' : ''}${g.plus_minus}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs" style={{ color: 'var(--text-muted)' }}>
        Incluye playoffs, play-in y NBA Cup: son los últimos partidos que jugó,
        no solo los de temporada regular. Haz clic en la fecha o el resultado
        para ver el partido completo.
      </p>
    </div>
  )
}

export function fmtRecord(g: RecentGame): string {
  return `${fmt(g.pts, 0)}-${fmt(g.reb, 0)}-${fmt(g.ast, 0)}`
}
