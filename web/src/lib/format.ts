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

/** Fecha con el día de la semana: "mar, 20 oct". Un calendario se lee por días. */
export function fmtDateWeekday(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleDateString('es-ES', { weekday: 'short', day: '2-digit', month: 'short' })
}

/**
 * La hora del salto inicial, en la zona de quien mira.
 *
 * Llega en UTC y se convierte en el navegador a propósito: quien consulta el
 * calendario desde España quiere saber a qué hora ha de encender la tele, no
 * qué hora era en el pabellón.
 *
 * Puede faltar, y no es un fallo: la NBA publica el día de los cruces de la
 * Copa mucho antes que la hora.
 */
export function fmtTime(utc: string | null | undefined): string {
  if (!utc) return '—'
  const d = new Date(utc)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })
}

/**
 * El día del partido para quien lo mira, no para el pabellón.
 *
 * LA FECHA Y LA HORA TIENEN QUE SALIR DEL MISMO RELOJ. `date` es la fecha en
 * la zona del ESTADIO —la que usa todo el análisis, y con razón— mientras que
 * la hora se muestra en la de quien consulta. Mezclarlas se ve bien desde
 * América y se contradice desde Europa: un partido de Los Ángeles que empieza
 * el martes a las 19:30 son las 04:30 del MIÉRCOLES en Madrid, y la fila
 * diría "martes, 04:30" — una hora a la que ese partido no se juega.
 *
 * Así que cuando hay salto inicial, el día se deriva de él. Sin salto inicial
 * —los cruces de la Copa, que se publican con el día decidido y la hora no—
 * se usa la fecha tal cual, que es lo único que hay.
 */
export function fmtGameDay(iso: string, utc: string | null | undefined): string {
  if (utc) {
    const d = new Date(utc)
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleDateString('es-ES', {
        weekday: 'short',
        day: '2-digit',
        month: 'short',
      })
    }
  }
  return fmtDateWeekday(iso)
}
