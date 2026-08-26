import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { StabilityComponent } from '../api/types'
import { Card, ErrorBox, Loading, Select } from '../components/Layout'

const COLOR: Record<string, string> = {
  habilidad: 'var(--status-good)',
  mixto: 'var(--status-warning)',
  suerte: 'var(--status-critical)',
  indistinguible: 'var(--text-muted)',
}

const FAMILIAS: Record<string, string> = {
  volumen: 'Cuánto haces',
  acierto: 'Si entra',
  control: 'Control del balón y del ritmo',
  origen: 'De dónde salen los puntos',
}

/**
 * Barra del peso que merece la media propia.
 *
 * Se enseña el peso y no `k` a secas porque `k=150` no dice nada por sí solo;
 * "con una temporada entera esto pesa 0,35" sí.
 */
function Peso({ valor, color }: { valor: number; color: string }) {
  return (
    <span className="inline-flex w-full items-center gap-2">
      <span
        className="relative h-2 flex-1 overflow-hidden"
        style={{ background: 'var(--surface-2)', borderRadius: 2 }}
      >
        <span
          className="absolute left-0 top-0 h-2"
          style={{ width: `${100 * valor}%`, background: color, borderRadius: 2 }}
        />
      </span>
      <span className="tabular w-10 text-right text-xs" style={{ color: 'var(--text-secondary)' }}>
        {valor.toFixed(2)}
      </span>
    </span>
  )
}

function Fila({ c }: { c: StabilityComponent }) {
  const color = COLOR[c.stability] ?? 'var(--text-muted)'
  return (
    <tr style={{ borderTop: '1px solid var(--border)' }}>
      <td className="py-2 pr-3">{c.label}</td>
      <td className="tabular py-2 pr-3 text-right font-medium">
        {c.k_games === null ? '—' : c.k_games.toFixed(1)}
      </td>
      <td className="py-2 pr-3">
        <span
          className="rounded px-1.5 py-0.5 text-xs"
          style={{
            color,
            background: `color-mix(in srgb, ${color} 14%, transparent)`,
          }}
        >
          {c.stability_label}
        </span>
      </td>
      <td className="w-40 py-2 pr-3">
        <Peso valor={c.weight_41} color={color} />
      </td>
      <td className="w-40 py-2">
        <Peso valor={c.weight_82} color={color} />
      </td>
    </tr>
  )
}

export function StabilityPage() {
  const [season, setSeason] = useState('')
  const cat = useQuery({ queryKey: ['catalog'], queryFn: () => api.catalog() })
  const t = useQuery({
    queryKey: ['stability', season],
    queryFn: () => api.stability(season || undefined),
  })

  if (t.error) return <ErrorBox error={t.error} />
  if (!t.data) return <Loading />

  const porFamilia = new Map<string, StabilityComponent[]>()
  for (const c of t.data.components) {
    if (!porFamilia.has(c.family)) porFamilia.set(c.family, [])
    porFamilia.get(c.family)!.push(c)
  }

  const temporadas = [
    { value: '', label: 'Todas' },
    ...(cat.data?.seasons ?? []).map((s) => ({ value: s, label: s })),
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Qué se repite y qué es la noche</h1>
        <p className="mt-1 max-w-3xl text-sm" style={{ color: 'var(--text-secondary)' }}>
          {t.data.note}
        </p>
      </div>

      {/* El par que justifica la tabla entera. Va arriba porque es la idea, no
          un ejemplo cualquiera. */}
      <Card title="El par que lo explica todo">
        <p className="max-w-3xl text-sm" style={{ color: 'var(--text-secondary)' }}>
          <strong style={{ color: 'var(--status-good)' }}>Cuántos triples concedes</strong> se
          estabiliza en <strong>8 partidos</strong>: es una decisión tuya, la defensa que eliges.{' '}
          <strong style={{ color: 'var(--status-critical)' }}>
            Que esos triples entren
          </strong>{' '}
          necesita <strong>150</strong>: más de una temporada, así que en un partido suelto es la
          noche. Son la misma jugada vista desde los dos lados, y por eso el motor de resultado
          esperado mantiene el volumen y sustituye solo el acierto.
        </p>
      </Card>

      <Card
        title="Partidos hasta creerse el dato"
        subtitle="k = partidos para que la media propia de un equipo pese la mitad. Las dos últimas columnas son ese peso con media temporada y con una entera."
        right={
          <Select label="Temporada" value={season} onChange={setSeason} options={temporadas} />
        }
      >
        {[...porFamilia.entries()].map(([familia, filas]) => (
          <div key={familia} className="mb-5 last:mb-0">
            <h3 className="mb-1 text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
              {FAMILIAS[familia] ?? familia}
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
                    <th className="py-1 pr-3 font-medium">Componente</th>
                    <th className="py-1 pr-3 text-right font-medium">k</th>
                    <th className="py-1 pr-3 font-medium">Clase</th>
                    <th className="py-1 pr-3 font-medium">Peso a 41 partidos</th>
                    <th className="py-1 font-medium">a 82</th>
                  </tr>
                </thead>
                <tbody>
                  {filas.map((c) => (
                    <Fila key={c.key} c={c} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
        <p className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          Por debajo de {t.data.boundaries.skill_max_k} partidos (media temporada) es habilidad; por
          encima de {t.data.boundaries.mixed_max_k} (temporada entera) es sobre todo azar. El corte
          no es una opinión: sale de descontar el ruido de muestreo de la dispersión observada, así
          que un componente donde todos los equipos parecen distintos pero no lo son cae del lado
          del azar aunque su varianza sea grande.
        </p>
      </Card>
    </div>
  )
}
