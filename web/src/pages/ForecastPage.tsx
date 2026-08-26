import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { CalibrationBin, TeamRating } from '../api/types'
import { Card, ErrorBox, Loading, Select } from '../components/Layout'
import { TeamLogo } from '../components/Media'
import { fmt, fmtSigned } from '../lib/format'

const pct = (v: number) => `${(100 * v).toFixed(1)}%`

/**
 * Barra divergente centrada en cero.
 *
 * Se usa para el neto y para el desglose del pronóstico: en los dos casos el
 * cero es el punto de referencia con significado (la media de la liga, o "no
 * aporta"), y una barra que crece desde la izquierda lo escondería.
 */
function BarraDivergente({ valor, max, color }: { valor: number; max: number; color: string }) {
  const ancho = Math.min(Math.abs(valor) / max, 1) * 50
  return (
    <span className="relative inline-block h-2 w-full align-middle">
      <span
        className="absolute top-0 h-2"
        style={{
          left: valor >= 0 ? '50%' : `${50 - ancho}%`,
          width: `${ancho}%`,
          background: color,
          borderRadius: 2,
        }}
      />
      <span
        className="absolute top-0 h-2"
        style={{ left: '50%', width: 1, background: 'var(--border)' }}
      />
    </span>
  )
}

function TablaRatings({ teams, maxNeto }: { teams: TeamRating[]; maxNeto: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
            <th className="py-2 pr-2 text-right font-medium">#</th>
            <th className="py-2 pr-3 font-medium">Equipo</th>
            <th className="py-2 pr-3 text-right font-medium" title="Puntos por 100 posesiones anotados por encima de la media">
              Ataque
            </th>
            <th className="py-2 pr-3 text-right font-medium" title="Puntos por 100 que evita respecto a la media. Más alto es mejor">
              Defensa
            </th>
            <th className="py-2 pr-3 text-right font-medium">Neto</th>
            <th className="py-2 w-40 font-medium" />
          </tr>
        </thead>
        <tbody>
          {teams.map((t, i) => (
            <tr key={t.team_id} style={{ borderTop: '1px solid var(--border)' }}>
              <td className="tabular py-2 pr-2 text-right" style={{ color: 'var(--text-muted)' }}>
                {i + 1}
              </td>
              <td className="py-2 pr-3">
                <Link
                  to={`/equipo/${t.team_id}`}
                  className="inline-flex items-center gap-2 hover:underline"
                  style={{ color: 'var(--series-1)' }}
                >
                  <TeamLogo teamId={t.team_id} name={t.abbreviation} size={20} />
                  {t.full_name}
                </Link>
              </td>
              <td className="tabular py-2 pr-3 text-right">{fmtSigned(t.offense, 1)}</td>
              <td className="tabular py-2 pr-3 text-right">{fmtSigned(t.defense, 1)}</td>
              <td
                className="tabular py-2 pr-3 text-right font-semibold"
                style={{ color: t.net > 0 ? 'var(--status-good)' : 'var(--status-critical)' }}
              >
                {fmtSigned(t.net, 1)}
              </td>
              <td className="py-2">
                <BarraDivergente
                  valor={t.net}
                  max={maxNeto}
                  color={t.net > 0 ? 'var(--status-good)' : 'var(--status-critical)'}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Diagrama de fiabilidad.
 *
 * Lo que hay que mirar es si el intervalo de la frecuencia REAL contiene lo que
 * el modelo prometió. Por eso se dibuja el intervalo y no solo el punto: sin él
 * cualquier ondulación parece un defecto, y con ~370 partidos por tramo el
 * margen de error es de ±4,6 puntos porcentuales.
 */
function TablaCalibracion({ bins }: { bins: CalibrationBin[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
            <th className="py-2 pr-3 font-medium">El modelo dice</th>
            <th className="py-2 pr-3 text-right font-medium">Partidos</th>
            <th className="py-2 pr-3 text-right font-medium">Prometido</th>
            <th className="py-2 pr-3 text-right font-medium">Real</th>
            <th className="py-2 pr-3 font-medium">IC 95% de lo real</th>
            <th className="py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {bins.map((b) => (
            <tr key={b.low} style={{ borderTop: '1px solid var(--border)' }}>
              <td className="tabular py-2 pr-3">
                {pct(b.low)} – {pct(b.high)}
              </td>
              <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--text-muted)' }}>
                {b.n}
              </td>
              <td className="tabular py-2 pr-3 text-right">{pct(b.predicted)}</td>
              <td className="tabular py-2 pr-3 text-right font-medium">{pct(b.observed)}</td>
              <td className="tabular py-2 pr-3" style={{ color: 'var(--text-secondary)' }}>
                [{pct(b.ci95_low)}, {pct(b.ci95_high)}]
              </td>
              <td className="py-2">
                <span
                  className="text-xs"
                  style={{ color: b.calibrated ? 'var(--status-good)' : 'var(--status-critical)' }}
                  title={
                    b.calibrated
                      ? 'El intervalo de la frecuencia real contiene lo prometido'
                      : 'Lo prometido cae fuera del intervalo de la frecuencia real'
                  }
                >
                  {b.calibrated ? '● dentro' : '● fuera'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ForecastPage() {
  const [local, setLocal] = useState('')
  const [visitante, setVisitante] = useState('')
  const [descLocal, setDescLocal] = useState('1')
  const [descVis, setDescVis] = useState('1')
  const [neutral, setNeutral] = useState(false)
  const [b2bLocal, setB2bLocal] = useState(false)
  const [b2bVis, setB2bVis] = useState(false)

  const ratings = useQuery({ queryKey: ['ratings'], queryFn: () => api.ratings() })
  const bt = useQuery({ queryKey: ['backtest'], queryFn: () => api.backtest() })

  const equipos = ratings.data?.teams ?? []
  const prediccion = useQuery({
    queryKey: ['predict', local, visitante, descLocal, descVis, neutral, b2bLocal, b2bVis],
    queryFn: () =>
      api.predict({
        home: Number(local),
        away: Number(visitante),
        neutral,
        rest_home: Number(descLocal),
        rest_away: Number(descVis),
        b2b_home: b2bLocal,
        b2b_away: b2bVis,
      }),
    enabled: Boolean(local && visitante && local !== visitante),
  })

  if (ratings.error) return <ErrorBox error={ratings.error} />
  if (!ratings.data) return <Loading />

  const maxNeto = Math.max(...equipos.map((t) => Math.abs(t.net)), 1)
  const opciones = [
    { value: '', label: '—' },
    ...[...equipos]
      .sort((a, b) => a.full_name.localeCompare(b.full_name))
      .map((t) => ({ value: String(t.team_id), label: t.full_name })),
  ]
  const dias = ['0', '1', '2', '3', '4'].map((d) => ({ value: d, label: `${d} días` }))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Fuerza y pronóstico</h1>
        <p className="mt-1 max-w-3xl text-sm" style={{ color: 'var(--text-secondary)' }}>
          {ratings.data.note}
        </p>
      </div>

      {/* --- Simulador --- */}
      <Card
        title="Simular un partido"
        subtitle={`Ratings al cierre de ${ratings.data.season}. La localía vale ${fmt(ratings.data.home_advantage_margin, 1)} puntos de margen.`}
      >
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <Select label="Local" value={local} onChange={setLocal} options={opciones} />
          <Select label="Visitante" value={visitante} onChange={setVisitante} options={opciones} />
          <Select label="Descanso local" value={descLocal} onChange={setDescLocal} options={dias} />
          <Select label="Descanso visit." value={descVis} onChange={setDescVis} options={dias} />
          <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
            <input type="checkbox" checked={neutral} onChange={(e) => setNeutral(e.target.checked)} />
            Sede neutral
          </label>
          {/* Existían en la API desde el principio y no había control: la fila
              "Segundo partido en 2 días" salía siempre a 0,00. */}
          <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
            <input type="checkbox" checked={b2bLocal} onChange={(e) => setB2bLocal(e.target.checked)} />
            Local en back-to-back
          </label>
          <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
            <input type="checkbox" checked={b2bVis} onChange={(e) => setB2bVis(e.target.checked)} />
            Visitante en back-to-back
          </label>
        </div>

        {prediccion.data && (
          <div className="mt-5">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className="text-3xl font-semibold">{pct(prediccion.data.home_win_prob)}</span>
              <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                gana {prediccion.data.home.abbreviation} · margen esperado{' '}
                <strong>{fmtSigned(prediccion.data.expected_margin, 1)}</strong>
              </span>
            </div>

            <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
              Modelo <code>{prediccion.data.model_version}</code>, entrenado con{' '}
              {prediccion.data.train_games.toLocaleString('es-ES')} partidos de temporadas
              anteriores. Rutas: logística {pct(prediccion.data.prob_logit)} · margen{' '}
              {pct(prediccion.data.prob_margin)}.
            </p>

            <div className="mt-4 max-w-lg">
              {prediccion.data.components.map((c) => (
                <div
                  key={c.key}
                  className="grid grid-cols-[11rem_4rem_1fr] items-center gap-3 py-1.5"
                  style={{ borderTop: '1px solid var(--border)' }}
                >
                  <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                    {c.label}
                  </span>
                  <span className="tabular text-right text-sm">{fmtSigned(c.points, 2)}</span>
                  <BarraDivergente
                    valor={c.points}
                    max={12}
                    color={c.points >= 0 ? 'var(--series-1)' : 'var(--series-2)'}
                  />
                </div>
              ))}
            </div>

            {/* Los avisos van visibles y completos: son parte del resultado, no
                una nota legal. El intervalo de ±27 puntos es la información
                más importante de toda la pantalla. */}
            <ul className="mt-4 max-w-3xl space-y-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
              {prediccion.data.warnings.map((w) => (
                <li key={w}>· {w}</li>
              ))}
            </ul>
          </div>
        )}

        {local && visitante && local === visitante && (
          <p className="mt-4 text-sm" style={{ color: 'var(--text-muted)' }}>
            Un equipo no juega contra sí mismo.
          </p>
        )}
      </Card>

      {/* --- Ratings --- */}
      <Card
        title={`Fuerza ajustada por rival · ${ratings.data.season}`}
        subtitle="Puntos por 100 posesiones respecto a la media de la liga. La defensa va en positivo: más alto es mejor."
      >
        <TablaRatings teams={equipos} maxNeto={maxNeto} />
      </Card>

      {/* --- Validación --- */}
      {bt.data && (
        <Card
          title="Qué tal predice, medido fuera de muestra"
          subtitle={`${bt.data.n.toLocaleString('es-ES')} partidos. Los ratings se reajustan por jornada y el modelo se entrena solo con temporadas anteriores.`}
        >
          <div className="grid gap-3 sm:grid-cols-4">
            {[
              ['Acierto', pct(bt.data.accuracy), `local siempre: ${pct(bt.data.baselines.always_home)}`],
              ['Brier', fmt(bt.data.brier, 4), `línea base: ${fmt(bt.data.baselines.always_home_brier, 4)}`],
              ['Log-loss', fmt(bt.data.log_loss, 4), `línea base: ${fmt(bt.data.baselines.always_home_log_loss, 4)}`],
              ['Brier Skill', fmt(bt.data.brier_skill_score, 3), '0 = no aporta nada'],
            ].map(([k, v, sub]) => (
              <div
                key={k}
                className="rounded-lg px-3.5 py-3"
                style={{ background: 'var(--surface-page)', border: '1px solid var(--border)' }}
              >
                <div className="text-[11px] uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>
                  {k}
                </div>
                <div className="mt-1 text-2xl font-semibold leading-none">{v}</div>
                <div className="mt-1 text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                  {sub}
                </div>
              </div>
            ))}
          </div>

          <p className="mt-4 max-w-3xl text-xs" style={{ color: 'var(--text-muted)' }}>
            {bt.data.caveat}
          </p>

          <div className="mt-6">
            <h3 className="text-sm font-semibold">¿Significa lo que dice?</h3>
            {/* El aviso va ANTES de la tabla, no después: es lo que impide leer
                la ondulación de la curva como si fuera información. */}
            <p className="mt-1 mb-3 max-w-3xl text-xs" style={{ color: 'var(--text-muted)' }}>
              {bt.data.calibration.note} Pendiente de calibración{' '}
              <strong>{fmt(bt.data.calibration.slope, 2)}</strong> (perfecto = 1), ECE{' '}
              <strong>{fmt(bt.data.calibration.ece, 4)}</strong> frente a un suelo de ruido de{' '}
              {fmt(bt.data.calibration.ece_noise_floor, 4)} — el ECE esperado bajo calibración
              perfecta no es cero.
            </p>
            <TablaCalibracion bins={bt.data.calibration.bins} />
            {bt.data.disagreements > 0 && (
              <p className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>
                En {bt.data.disagreements} partidos las dos rutas de cálculo —logística sobre el
                resultado y normal sobre el margen— difieren en más de 3 puntos porcentuales. La
                probabilidad publicada es la media de las dos.
              </p>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}
