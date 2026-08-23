import type { Reliability } from '../api/types'
import { RELIABILITY_LABEL } from '../lib/format'

/**
 * Insignia de confiabilidad.
 *
 * Va acompañada SIEMPRE de texto, nunca solo de color: los colores de estado no
 * llegan a 3:1 de contraste en modo claro por diseño, y el emparejamiento
 * icono + etiqueta es la mitigación. Además, un lector daltónico no debe
 * depender del tono para saber si un número es sólido.
 */
export function ReliabilityBadge({
  reliability,
  n,
}: {
  reliability: Reliability
  n: number
}) {
  const solida = reliability === 'alta'
  const debil = reliability === 'baja' || reliability === 'insuficiente'

  const color = solida
    ? 'var(--status-good)'
    : debil
      ? 'var(--status-warning)'
      : 'var(--text-muted)'

  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap"
      style={{ color: 'var(--text-secondary)' }}
      title={`${RELIABILITY_LABEL[reliability]} · n=${n} partidos`}
    >
      <span aria-hidden style={{ color }}>
        {solida ? '●' : debil ? '▲' : '◐'}
      </span>
      <span className="tabular">n={n}</span>
    </span>
  )
}

/**
 * Aviso de que un resultado no se distingue del azar.
 *
 * Este componente es el motivo por el que existe el proyecto. La tentación es
 * enseñar «14,2 rebotes los domingos» en grande porque queda bien; ese número
 * es ruido y hay que decirlo donde se ve.
 */
export function NoiseWarning({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex gap-2.5 rounded-lg px-3.5 py-3 text-sm leading-relaxed"
      style={{
        background: 'color-mix(in srgb, var(--status-warning) 12%, transparent)',
        color: 'var(--text-secondary)',
        border: '1px solid color-mix(in srgb, var(--status-warning) 35%, transparent)',
      }}
      role="note"
    >
      <span aria-hidden style={{ color: 'var(--status-warning)' }}>▲</span>
      <div>{children}</div>
    </div>
  )
}
