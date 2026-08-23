import { Link } from 'react-router-dom'
import type { Player, PlayerRanks, RankedStat } from '../api/types'
import { fmt, fmtPct } from '../lib/format'
import { PlayerPhoto, TeamLogo } from './Media'

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

export function PlayerHeader({ p }: { p: Player }) {
  const activo = p.roster_status === 'Active'

  const draft =
    p.draft_year && p.draft_round && p.draft_number
      ? `${p.draft_year}: Rd ${p.draft_round}, Sel. ${p.draft_number}`
      : p.draft_year
        ? `${p.draft_year}`
        : 'No drafteado'

  const nacimiento = p.birthdate
    ? `${new Date(`${p.birthdate}T00:00:00`).toLocaleDateString('es-ES')}${
        p.age ? ` (${Math.floor(p.age)})` : ''
      }`
    : null

  const talla =
    p.height_cm && p.weight_kg
      ? `${(p.height_cm / 100).toFixed(2)} m, ${p.weight_kg} kg`
      : null

  return (
    <section
      className="rounded-xl p-5"
      style={{ background: 'var(--surface-1)', border: '1px solid var(--border)' }}
    >
      <div className="flex flex-wrap items-start gap-5">
        <PlayerPhoto playerId={p.player_id} name={p.full_name} size={104} large />

        <div className="min-w-56 flex-1">
          <h1 className="text-2xl font-semibold leading-tight tracking-tight">
            {p.full_name}
          </h1>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm">
            {p.current_team_id && (
              <Link
                to={`/equipo/${p.current_team_id}`}
                className="inline-flex items-center gap-1.5 hover:underline"
                style={{ color: 'var(--series-1)' }}
              >
                <TeamLogo
                  teamId={p.current_team_id}
                  name={p.current_team_name ?? ''}
                  size={22}
                />
                {p.current_team_name}
              </Link>
            )}
            {p.jersey_number && (
              <span style={{ color: 'var(--text-secondary)' }}>#{p.jersey_number}</span>
            )}
            {p.position && (
              <span style={{ color: 'var(--text-secondary)' }}>{p.position}</span>
            )}
          </div>

          {/* Estatus con punto Y palabra: el color solo no sirve a quien no lo
              distingue, y los tonos de estado no llegan a 3:1 en modo claro. */}
          {p.roster_status && (
            <div className="mt-2 inline-flex items-center gap-1.5 text-sm">
              <span
                aria-hidden
                style={{ color: activo ? 'var(--status-good)' : 'var(--text-muted)' }}
              >
                ●
              </span>
              <span style={{ color: 'var(--text-secondary)' }}>
                {activo ? 'Activo' : 'Inactivo'}
              </span>
            </div>
          )}
        </div>

        <dl className="grid shrink-0 grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3">
          <Dato etiqueta="Est/Pes" valor={talla} />
          <Dato etiqueta="Nacimiento" valor={nacimiento} />
          <Dato etiqueta="Info draft" valor={draft} />
          <Dato
            etiqueta="Experiencia"
            valor={
              p.season_experience !== null
                ? p.season_experience === 0
                  ? 'Novato'
                  : `${p.season_experience}ª temporada`
                : null
            }
          />
          <Dato etiqueta="Procedencia" valor={p.school} />
          <Dato etiqueta="País" valor={p.country} />
        </dl>
      </div>
    </section>
  )
}

function ordinal(n: number): string {
  return `${n}º`
}

function Tile({
  etiqueta,
  stat,
  esPct = false,
}: {
  etiqueta: string
  stat: RankedStat
  esPct?: boolean
}) {
  return (
    <div
      className="rounded-lg px-3.5 py-3 text-center"
      style={{ background: 'var(--surface-page)', border: '1px solid var(--border)' }}
    >
      <div className="text-[11px] uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>
        {etiqueta}
      </div>
      {/* Cifra suelta: figuras proporcionales, nunca tabulares. */}
      <div className="mt-1 text-2xl font-semibold leading-none">
        {esPct ? fmtPct(stat.value) : fmt(stat.value, 1)}
      </div>
      <div className="mt-1 text-[11px]" style={{ color: 'var(--text-secondary)' }}>
        {stat.rank ? ordinal(stat.rank) : '—'}
      </div>
    </div>
  )
}

export function SeasonTiles({ ranks }: { ranks: PlayerRanks }) {
  return (
    <div>
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7">
        <Tile etiqueta="PTS" stat={ranks.pts} />
        <Tile etiqueta="REB" stat={ranks.reb} />
        <Tile etiqueta="AST" stat={ranks.ast} />
        <Tile etiqueta="ROB" stat={ranks.stl} />
        <Tile etiqueta="TAP" stat={ranks.blk} />
        <Tile etiqueta="FG%" stat={ranks.fg_pct} esPct />
        <Tile etiqueta="TS%" stat={ranks.ts_pct} esPct />
      </div>
      <p className="mt-2 text-xs" style={{ color: 'var(--text-muted)' }}>
        Puesto sobre {ranks.qualified_players} jugadores cualificados según la regla
        oficial de la NBA (58 partidos, el 70% de la temporada).{' '}
        {ranks.games_played} partidos disputados. Los puestos de FG% y TS% pueden
        diferir de los publicados: la NBA los calcula con mínimos de intentos, no de
        partidos.
      </p>
    </div>
  )
}
