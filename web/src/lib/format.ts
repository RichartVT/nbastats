import type { Reliability } from '../api/types'

export function fmt(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toFixed(decimals)
}

export function fmtSigned(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(decimals)}`
}

/** Los porcentajes llegan como fracción (0.597) y se muestran como 59.7%. */
export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(1)}%`
}

export function isPctStat(stat: string): boolean {
  return stat.endsWith('_pct')
}

export function fmtStat(v: number | null | undefined, stat: string): string {
  return isPctStat(stat) ? fmtPct(v) : fmt(v)
}

export const RELIABILITY_LABEL: Record<Reliability, string> = {
  alta: 'Muestra amplia',
  media: 'Muestra media',
  baja: 'Muestra pequeña',
  insuficiente: 'Muestra insuficiente',
}

export function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: '2-digit' })
}
