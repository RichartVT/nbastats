import { NavLink, Outlet } from 'react-router-dom'

const enlaces = [
  { to: '/', label: 'Jugadores', end: true },
  { to: '/equipos', label: 'Equipos' },
  { to: '/clasificacion', label: 'Clasificación' },
  { to: '/comparar', label: 'Comparar' },
  { to: '/tendencias', label: 'Al alza y en declive' },
]

export function Layout() {
  return (
    <div className="min-h-full">
      <header style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="mx-auto flex max-w-6xl flex-wrap items-baseline gap-x-8 gap-y-2 px-6 py-4">
          <NavLink to="/" className="text-base font-semibold tracking-tight">
            Estadísticas NBA
          </NavLink>
          <nav className="flex gap-5 text-sm">
            {enlaces.map((e) => (
              <NavLink
                key={e.to}
                to={e.to}
                end={e.end}
                style={({ isActive }) => ({
                  color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontWeight: isActive ? 600 : 400,
                })}
              >
                {e.label}
              </NavLink>
            ))}
          </nav>
          <span className="ml-auto text-xs" style={{ color: 'var(--text-muted)' }}>
            5 temporadas · 6.602 partidos
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}

export function Card({
  title,
  subtitle,
  right,
  children,
}: {
  title?: string
  subtitle?: string
  right?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section
      className="rounded-xl p-5"
      style={{ background: 'var(--surface-1)', border: '1px solid var(--border)' }}
    >
      {(title || right) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {subtitle && (
              <p className="mt-0.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
                {subtitle}
              </p>
            )}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  )
}

export function Select({
  value,
  onChange,
  options,
  label,
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
  label: string
}) {
  return (
    <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md px-2.5 py-1.5 text-xs"
        style={{
          background: 'var(--surface-1)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border)',
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function Loading() {
  return (
    <p className="py-8 text-sm" style={{ color: 'var(--text-muted)' }}>
      Cargando…
    </p>
  )
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <div
      className="rounded-lg px-4 py-3 text-sm"
      style={{
        background: 'color-mix(in srgb, var(--status-critical) 10%, transparent)',
        border: '1px solid color-mix(in srgb, var(--status-critical) 35%, transparent)',
      }}
    >
      <strong style={{ color: 'var(--status-critical)' }}>Error.</strong>{' '}
      <span style={{ color: 'var(--text-secondary)' }}>{msg}</span>
      <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
        ¿Está corriendo la API? <code>uv run uvicorn nbastats.api.main:app</code>
      </p>
    </div>
  )
}
