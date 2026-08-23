import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { TeamBoxScore } from '../api/types'
import { Card, ErrorBox, Loading } from '../components/Layout'
import { GameTypeBadge, PlayerPhoto, TeamLogo } from '../components/Media'
import { fmt, fmtDate, fmtPct, fmtSigned } from '../lib/format'

type Vista = 'basicas' | 'avanzadas'

function pct(m: number | null, a: number | null): string {
  if (!a) return '—'
  return `${(((m ?? 0) / a) * 100).toFixed(1)}%`
}

/**
 * Fila de comparación entre los dos equipos, con la ventaja resaltada.
 *
 * Recibe los valores para COMPARAR y, aparte, los textos para MOSTRAR. Separar
 * las dos cosas es lo que permite que una fila enseñe "31/87 (35,6%)" mientras
 * decide el ganador con los aciertos: si el componente tuviera que deducir el
 * texto del número, cada fila con un formato compuesto necesitaría un apaño.
 */
function Comparativa({
  etiqueta,
  visitante,
  local,
  textoVisitante,
  textoLocal,
  mejorEsMayor = true,
  decimales = 1,
}: {
  etiqueta: string
  visitante: number | null
  local: number | null
  textoVisitante?: string
  textoLocal?: string
  mejorEsMayor?: boolean
  decimales?: number
}) {
  let gana: 'v' | 'l' | null = null
  if (visitante !== null && local !== null && visitante !== local) {
    const visitanteGana = mejorEsMayor ? visitante > local : visitante < local
    gana = visitanteGana ? 'v' : 'l'
  }

  const estilo = (lado: 'v' | 'l') => ({
    fontWeight: gana === lado ? 600 : 400,
    color: gana === lado ? 'var(--text-primary)' : 'var(--text-secondary)',
  })

  return (
    <div
      className="grid grid-cols-[1fr_9rem_1fr] items-center gap-3 py-1.5"
      style={{ borderTop: '1px solid var(--border)' }}
    >
      <div className="tabular text-right text-sm" style={estilo('v')}>
        {textoVisitante ?? fmt(visitante, decimales)}
      </div>
      <div className="text-center text-xs" style={{ color: 'var(--text-muted)' }}>
        {etiqueta}
      </div>
      <div className="tabular text-left text-sm" style={estilo('l')}>
        {textoLocal ?? fmt(local, decimales)}
      </div>
    </div>
  )
}

function BoxScore({ equipo, vista }: { equipo: TeamBoxScore; vista: Vista }) {
  const titulares = equipo.players.filter((p) => p.started)
  const suplentes = equipo.players.filter((p) => !p.started)
  // `started` está vacío en esta fuente (ver CAPABILITIES.md §2), así que si no
  // hay titulares marcados se listan todos juntos, por minutos.
  const grupos = titulares.length
    ? [
        { nombre: 'Titulares', jugadores: titulares },
        { nombre: 'Banquillo', jugadores: suplentes },
      ]
    : [{ nombre: '', jugadores: equipo.players }]

  const cabeceras =
    vista === 'basicas'
      ? ['Min', 'PTS', 'TC', '3P', 'TL', 'REB', 'AST', 'ROB', 'TAP', 'PER', 'FP', '+/-']
      : ['Min', 'TS%', 'eFG%', 'USG%', 'AST%', 'REB%', 'Of', 'Def', 'Net', 'PIE', 'GmSc']

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
            <th className="py-2 pr-3 font-medium">Jugador</th>
            {cabeceras.map((h) => (
              <th key={h} className="py-2 pr-3 text-right font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grupos.map(({ nombre, jugadores }) => (
            <Fragment key={nombre || 'todos'}>
              {nombre && (
                <tr>
                  <td
                    colSpan={cabeceras.length + 1}
                    className="pt-3 pb-1 text-xs uppercase tracking-wide"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    {nombre}
                  </td>
                </tr>
              )}
              {jugadores.map((p) => (
                <tr key={p.player_id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td className="py-2 pr-3">
                    <Link
                      to={`/jugador/${p.player_id}`}
                      className="inline-flex items-center gap-2 whitespace-nowrap hover:underline"
                      style={{ color: 'var(--series-1)' }}
                    >
                      <PlayerPhoto playerId={p.player_id} name={p.full_name} size={26} />
                      {p.full_name}
                      {p.jersey_number && (
                        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                          #{p.jersey_number}
                        </span>
                      )}
                    </Link>
                  </td>
                  {vista === 'basicas' ? (
                    <>
                      <td className="tabular py-2 pr-3 text-right">{p.minutes}</td>
                      <td className="tabular py-2 pr-3 text-right font-medium">{p.pts}</td>
                      <td className="tabular py-2 pr-3 text-right">
                        {p.fgm}/{p.fga}
                      </td>
                      <td className="tabular py-2 pr-3 text-right">
                        {p.fg3m}/{p.fg3a}
                      </td>
                      <td className="tabular py-2 pr-3 text-right">
                        {p.ftm}/{p.fta}
                      </td>
                      <td className="tabular py-2 pr-3 text-right">{p.reb}</td>
                      <td className="tabular py-2 pr-3 text-right">{p.ast}</td>
                      <td className="tabular py-2 pr-3 text-right">{p.stl}</td>
                      <td className="tabular py-2 pr-3 text-right">{p.blk}</td>
                      <td className="tabular py-2 pr-3 text-right">{p.tov}</td>
                      <td className="tabular py-2 pr-3 text-right">{p.pf}</td>
                      <td
                        className="tabular py-2 pr-3 text-right"
                        style={{
                          color:
                            (p.plus_minus ?? 0) > 0
                              ? 'var(--status-good)'
                              : (p.plus_minus ?? 0) < 0
                                ? 'var(--status-critical)'
                                : 'var(--text-secondary)',
                        }}
                      >
                        {p.plus_minus === null ? '—' : fmtSigned(p.plus_minus, 0)}
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="tabular py-2 pr-3 text-right">{p.minutes}</td>
                      <td className="tabular py-2 pr-3 text-right">{fmtPct(p.ts_pct)}</td>
                      <td className="tabular py-2 pr-3 text-right">{fmtPct(p.efg_pct)}</td>
                      <td className="tabular py-2 pr-3 text-right">{fmtPct(p.usg_pct)}</td>
                      <td className="tabular py-2 pr-3 text-right">{fmtPct(p.ast_pct)}</td>
                      <td className="tabular py-2 pr-3 text-right">{fmtPct(p.reb_pct)}</td>
                      <td className="tabular py-2 pr-3 text-right">{fmt(p.off_rating, 0)}</td>
                      <td className="tabular py-2 pr-3 text-right">{fmt(p.def_rating, 0)}</td>
                      <td className="tabular py-2 pr-3 text-right">
                        {fmtSigned(p.net_rating, 0)}
                      </td>
                      <td className="tabular py-2 pr-3 text-right">{fmtPct(p.pie)}</td>
                      <td className="tabular py-2 pr-3 text-right">{fmt(p.game_score, 1)}</td>
                    </>
                  )}
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function GamePage() {
  const { id } = useParams()
  const [vista, setVista] = useState<Vista>('basicas')

  const { data, isLoading, error } = useQuery({
    queryKey: ['game', id],
    queryFn: () => api.game(id as string),
    enabled: Boolean(id),
  })

  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) return <Loading />

  const { home: local, away: visitante } = data

  const Marcador = ({ t, ganador }: { t: TeamBoxScore; ganador: boolean }) => (
    <Link
      to={`/equipo/${t.team_id}`}
      className="flex flex-1 items-center gap-3 hover:underline"
      style={{ color: 'var(--text-primary)' }}
    >
      <TeamLogo teamId={t.team_id} name={t.full_name} size={48} />
      <div className="min-w-0">
        <div className="truncate font-medium">{t.full_name}</div>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {t.is_home ? 'Local' : 'Visitante'}
          {t.is_back_to_back && ' · 2º en 2 días'}
          {t.rest_days !== null &&
            t.rest_days > 0 &&
            ` · ${t.rest_days} ${t.rest_days === 1 ? 'día' : 'días'} de descanso`}
        </div>
      </div>
      <div
        className="ml-auto text-3xl font-semibold"
        style={{ color: ganador ? 'var(--text-primary)' : 'var(--text-muted)' }}
      >
        {t.pts}
      </div>
    </Link>
  )

  return (
    <div className="space-y-6">
      {/* --- Marcador --- */}
      <section
        className="rounded-xl p-5"
        style={{ background: 'var(--surface-1)', border: '1px solid var(--border)' }}
      >
        <div
          className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
          style={{ color: 'var(--text-secondary)' }}
        >
          <span>{fmtDate(data.date)}</span>
          <GameTypeBadge type={data.game_type} />
          {data.ot_periods > 0 && (
            <span>{data.ot_periods === 1 ? 'Prórroga' : `${data.ot_periods} prórrogas`}</span>
          )}
          {data.is_neutral_site && <span>Sede neutral</span>}
          {data.attendance && <span>{data.attendance.toLocaleString('es-ES')} espectadores</span>}
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <Marcador t={visitante} ganador={Boolean(visitante.won)} />
          <span className="text-center text-sm" style={{ color: 'var(--text-muted)' }}>
            @
          </span>
          <Marcador t={local} ganador={Boolean(local.won)} />
        </div>
      </section>

      {/* --- Comparativa de equipo --- */}
      <Card
        title="Comparativa"
        subtitle={`${visitante.abbreviation} (visitante)  ·  ${local.abbreviation} (local)`}
      >
        <div>
          {/* En los tiros se compara por ACIERTOS y se muestra el intento
              completo con su porcentaje: 12/37 dice más que 32,4%. */}
          <Comparativa
            etiqueta="Tiros de campo"
            visitante={visitante.fgm}
            local={local.fgm}
            textoVisitante={`${visitante.fgm}/${visitante.fga} · ${pct(visitante.fgm, visitante.fga)}`}
            textoLocal={`${local.fgm}/${local.fga} · ${pct(local.fgm, local.fga)}`}
          />
          <Comparativa
            etiqueta="Triples"
            visitante={visitante.fg3m}
            local={local.fg3m}
            textoVisitante={`${visitante.fg3m}/${visitante.fg3a} · ${pct(visitante.fg3m, visitante.fg3a)}`}
            textoLocal={`${local.fg3m}/${local.fg3a} · ${pct(local.fg3m, local.fg3a)}`}
          />
          <Comparativa
            etiqueta="Tiros libres"
            visitante={visitante.ftm}
            local={local.ftm}
            textoVisitante={`${visitante.ftm}/${visitante.fta} · ${pct(visitante.ftm, visitante.fta)}`}
            textoLocal={`${local.ftm}/${local.fta} · ${pct(local.ftm, local.fta)}`}
          />
          <Comparativa
            etiqueta="Rebotes"
            visitante={visitante.reb}
            local={local.reb}
            decimales={0}
          />
          <Comparativa
            etiqueta="Rebotes ofensivos"
            visitante={visitante.oreb}
            local={local.oreb}
            decimales={0}
          />
          <Comparativa
            etiqueta="Asistencias"
            visitante={visitante.ast}
            local={local.ast}
            decimales={0}
          />
          <Comparativa
            etiqueta="Robos"
            visitante={visitante.stl}
            local={local.stl}
            decimales={0}
          />
          <Comparativa
            etiqueta="Tapones"
            visitante={visitante.blk}
            local={local.blk}
            decimales={0}
          />
          <Comparativa
            etiqueta="Pérdidas"
            visitante={visitante.tov}
            local={local.tov}
            mejorEsMayor={false}
            decimales={0}
          />
          <Comparativa
            etiqueta="Faltas"
            visitante={visitante.pf}
            local={local.pf}
            mejorEsMayor={false}
            decimales={0}
          />
          <Comparativa
            etiqueta="TS%"
            visitante={visitante.ts_pct}
            local={local.ts_pct}
            textoVisitante={fmtPct(visitante.ts_pct)}
            textoLocal={fmtPct(local.ts_pct)}
          />
          <Comparativa
            etiqueta="Rating ofensivo"
            visitante={visitante.off_rating}
            local={local.off_rating}
          />
          <Comparativa
            etiqueta="Posesiones"
            visitante={visitante.possessions}
            local={local.possessions}
            decimales={0}
          />
        </div>
        <p className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          El ritmo del partido fue de {fmt(local.pace, 1)} posesiones por 48 minutos —
          es el mismo para los dos equipos, porque comparten el balón.
        </p>
      </Card>

      {/* --- Box scores --- */}
      <div className="flex items-center gap-3">
        <h2 className="text-sm font-semibold">Box score</h2>
        <div className="flex gap-1">
          {(['basicas', 'avanzadas'] as const).map((v) => (
            <button
              key={v}
              onClick={() => setVista(v)}
              className="rounded-md px-2.5 py-1.5 text-xs"
              style={{
                background: vista === v ? 'var(--series-1)' : 'var(--surface-1)',
                color: vista === v ? '#fff' : 'var(--text-secondary)',
                border: '1px solid var(--border)',
              }}
            >
              {v === 'basicas' ? 'Básicas' : 'Avanzadas'}
            </button>
          ))}
        </div>
      </div>

      {[visitante, local].map((t) => (
        <Card
          key={t.team_id}
          title={t.full_name}
          subtitle={`${t.is_home ? 'Local' : 'Visitante'} · ${t.pts} puntos · ${
            t.players.length
          } jugadores`}
        >
          <BoxScore equipo={t} vista={vista} />
        </Card>
      ))}

      <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
        Esto es <strong>todo</strong> lo que hay de este partido en la base. No existe
        desglose por cuarto, ni secuencia de anotación, ni datos de tiro por zona:
        eso requeriría cargar el play-by-play, que está documentado en
        CAPABILITIES.md §2 con su coste.
      </p>
    </div>
  )
}
