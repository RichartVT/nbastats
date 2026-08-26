import { useState } from 'react'
import type { GameType, PlayerStatus } from '../api/types'

/**
 * Imágenes enlazadas al CDN de la NBA.
 *
 * No se guarda ninguna URL en la base: se derivan del id. Guardar una URL
 * calculable solo añade una copia que se queda obsoleta cuando la NBA cambia
 * el patrón, y no ahorra nada. Coste en disco: cero — las descarga el
 * navegador, ~15 KB una foto y ~10 KB un logo.
 *
 * A cambio, dependen de que cdn.nba.com esté accesible. Por eso cada
 * componente lleva su propia reserva: un fallo del CDN degrada la página, no
 * la rompe.
 */

const HEADSHOT = (id: number, size: '260x190' | '1040x760' = '260x190') =>
  `https://cdn.nba.com/headshots/nba/latest/${size}/${id}.png`

const TEAM_LOGO = (id: number) =>
  `https://cdn.nba.com/logos/nba/${id}/primary/L/logo.svg`

function iniciales(nombre: string): string {
  return nombre
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('')
}

export function PlayerPhoto({
  playerId,
  name,
  size = 64,
  large = false,
}: {
  playerId: number
  name: string
  size?: number
  large?: boolean
}) {
  const [falló, setFalló] = useState(false)

  if (falló) {
    return (
      <div
        className="flex shrink-0 items-center justify-center rounded-full font-semibold"
        style={{
          width: size,
          height: size,
          fontSize: size * 0.34,
          background: 'var(--surface-page)',
          color: 'var(--text-muted)',
          border: '1px solid var(--border)',
        }}
        aria-label={name}
      >
        {iniciales(name)}
      </div>
    )
  }

  return (
    <img
      src={HEADSHOT(playerId, large ? '1040x760' : '260x190')}
      alt={name}
      onError={() => setFalló(true)}
      loading="lazy"
      className="shrink-0 rounded-full object-cover object-top"
      style={{
        width: size,
        height: size,
        background: 'var(--surface-page)',
        border: '1px solid var(--border)',
      }}
    />
  )
}

export function TeamLogo({
  teamId,
  name,
  size = 28,
}: {
  teamId: number
  name: string
  size?: number
}) {
  const [falló, setFalló] = useState(false)

  if (falló) {
    return (
      <span
        className="inline-block shrink-0 text-center font-semibold"
        style={{ width: size, fontSize: size * 0.4, color: 'var(--text-muted)' }}
        aria-label={name}
      >
        {name.slice(0, 3)}
      </span>
    )
  }

  return (
    <img
      src={TEAM_LOGO(teamId)}
      alt={name}
      title={name}
      onError={() => setFalló(true)}
      loading="lazy"
      className="shrink-0 object-contain"
      style={{ width: size, height: size }}
    />
  )
}

/**
 * Situación del jugador: en plantilla, sin equipo o fuera de la liga.
 *
 * Punto Y palabra, nunca solo el color: los tonos de estado no llegan a 3:1 de
 * contraste en modo claro, y quien no distingue verde de gris se quedaría sin
 * la información. El `title` lleva la nota completa del backend, que es donde
 * está el matiz — "puede estar retirado o jugando fuera de la NBA".
 */
const COLOR_ESTADO: Record<string, string> = {
  activo: 'var(--status-good)',
  agente_libre: 'var(--status-warning)',
  fuera_liga: 'var(--text-muted)',
  sin_datos: 'var(--text-muted)',
}

export function StatusBadge({
  status,
  size = 'sm',
}: {
  status: PlayerStatus
  size?: 'sm' | 'md'
}) {
  const color = COLOR_ESTADO[status.key] ?? 'var(--text-muted)'
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap ${
        size === 'md' ? 'text-sm' : 'text-xs'
      }`}
      title={status.note}
    >
      <span aria-hidden style={{ color, lineHeight: 1 }}>
        ●
      </span>
      <span style={{ color: 'var(--text-secondary)' }}>{status.label}</span>
    </span>
  )
}

/**
 * Insignia con el tipo de partido.
 *
 * Los partidos de temporada regular NO llevan insignia: son la inmensa mayoría
 * y marcarlos todos con una etiqueta gris convierte la tabla en ruido. La
 * insignia solo aparece cuando el partido es distinto de lo normal, que es
 * cuando aporta información.
 */
export function GameTypeBadge({ type }: { type: GameType }) {
  if (type.key === 'regular') return null

  const color =
    type.key === 'playoffs' || type.key === 'playin'
      ? 'var(--series-2)'
      : type.key === 'cup'
        ? 'var(--series-4)'
        : 'var(--series-3)'

  return (
    <span
      className="inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium"
      style={{
        color,
        background: `color-mix(in srgb, ${color} 14%, transparent)`,
        border: `1px solid color-mix(in srgb, ${color} 32%, transparent)`,
      }}
    >
      {type.label}
    </span>
  )
}

/** Victoria o derrota, con letra además de color. */
export function WinLoss({ won }: { won: boolean | null }) {
  if (won === null) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  return (
    <span
      className="font-semibold"
      style={{ color: won ? 'var(--status-good)' : 'var(--status-critical)' }}
    >
      {won ? 'G' : 'P'}
    </span>
  )
}
