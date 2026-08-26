import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { GameDetail, TeamBoxScore } from '../api/types'
import { Card, ErrorBox, Loading } from '../components/Layout'
import { GameTypeBadge, PlayerPhoto, TeamLogo } from '../components/Media'
import { fmt, fmtDate, fmtPct, fmtSigned } from '../lib/format'

type Vista = 'basicas' | 'avanzadas' | 'cuartos'

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

/**
 * Marcador por cuartos.
 *
 * No se pinta si `periods` viene vacío: eso significa que el resumen del
 * partido todavía no se ha descargado (`nbastats ingest-summaries`), no que el
 * partido no tuviera cuartos. Una tabla de ceros sería un dato inventado.
 *
 * Las columnas de prórroga se etiquetan P1, P2… en vez de 5, 6: es como se lee
 * un marcador, y además el número de periodo ya no significa nada para quien
 * mira ("¿el 6?" no dice que fue la segunda prórroga).
 */
function MarcadorPorCuartos({ data }: { data: GameDetail }) {
  if (data.periods.length === 0) return null

  const periodos = [...new Set(data.periods.map((p) => p.period))].sort((a, b) => a - b)
  const esProrroga = (n: number) =>
    data.periods.find((p) => p.period === n)?.is_overtime ?? false

  const puntos = (teamId: number, periodo: number) =>
    data.periods.find((p) => p.team_id === teamId && p.period === periodo)?.points

  const filas = [data.away, data.home]
  let prorroga = 0
  const etiquetas = periodos.map((n) => (esProrroga(n) ? `P${++prorroga}` : String(n)))

  return (
    <div className="mt-4 overflow-x-auto" style={{ borderTop: '1px solid var(--border)' }}>
      <table className="mt-3 text-sm">
        <thead>
          <tr style={{ color: 'var(--text-muted)' }}>
            <th className="w-16 py-1 pr-3 text-left font-medium" />
            {periodos.map((n, i) => (
              <th
                key={n}
                className="w-11 py-1 text-right font-medium"
                title={esProrroga(n) ? `Prórroga ${etiquetas[i].slice(1)}` : `Cuarto ${n}`}
              >
                {etiquetas[i]}
              </th>
            ))}
            <th className="w-14 py-1 pr-1 text-right font-medium">T</th>
          </tr>
        </thead>
        <tbody>
          {filas.map((t) => (
            <tr key={t.team_id} style={{ borderTop: '1px solid var(--border)' }}>
              <td className="py-1.5 pr-3 font-medium">{t.abbreviation}</td>
              {periodos.map((n) => {
                // El máximo del periodo se resalta: es lo que convierte la
                // tabla en una lectura del partido y no en doce cifras.
                const mio = puntos(t.team_id, n)
                const rival = filas.find((o) => o.team_id !== t.team_id)
                const suyo = rival ? puntos(rival.team_id, n) : undefined
                const gana = mio !== undefined && suyo !== undefined && mio > suyo
                return (
                  <td
                    key={n}
                    className="tabular py-1.5 text-right"
                    style={{
                      color: gana ? 'var(--text-primary)' : 'var(--text-secondary)',
                      fontWeight: gana ? 600 : 400,
                    }}
                  >
                    {mio ?? '—'}
                  </td>
                )
              })}
              <td className="tabular py-1.5 pr-1 text-right font-semibold">{t.pts}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function BoxScore({
  equipo,
  vista,
  periodos,
}: {
  equipo: TeamBoxScore
  vista: Vista
  periodos: { numero: number; etiqueta: string }[]
}) {
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
      : vista === 'cuartos'
        ? ['Min', ...periodos.map((x) => x.etiqueta), 'PTS']
        : ['Min', 'TS%', 'eFG%', 'USG%', 'AST%', 'REB%', 'Of', 'Def', 'Net', 'PIE', 'GmSc']

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
            <th className="py-2 pr-3 font-medium">Jugador</th>
            {cabeceras.map((h, i) => (
              <th
                key={h}
                // Las columnas de una tabla se ajustan a su contenido, así que
                // un cuarto con "11" ensanchaba SOLO esa columna y descuadraba
                // la rejilla — dentro de la tabla y entre los dos equipos. Con
                // ancho fijo, un cuarto de 2 puntos y otro de 12 ocupan lo
                // mismo y las cifras caen siempre en la misma vertical.
                //
                // Solo las de cuarto: "Min" lleva "41:54" y no cabe en el mismo
                // ancho, y forzárselo la rompería en dos líneas.
                className={`py-2 pr-3 text-right font-medium ${
                  vista === 'cuartos' && i > 0 && i <= periodos.length ? 'w-14' : ''
                }`}
              >
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
                  ) : vista === 'cuartos' ? (
                    <>
                      <td className="tabular py-2 pr-3 text-right">{p.minutes}</td>
                      {periodos.map(({ numero }) => {
                        // Sin entrada = no jugó ese cuarto, que NO es lo mismo
                        // que anotar cero. Un 0 ahí diría que estuvo en pista
                        // sin anotar, y sería mentira.
                        const pts = p.points_by_period[String(numero)]
                        const jugo = pts !== undefined
                        return (
                          <td
                            key={numero}
                            className="tabular w-14 py-2 pr-3 text-right"
                            style={{
                              // El énfasis del cuarto de dos dígitos va por
                              // COLOR y no por grosor: la negrita tiene otras
                              // métricas que la redonda, así que `tabular-nums`
                              // deja de igualar los anchos en cuanto se mezclan
                              // y las cifras dejan de alinearse entre sí.
                              color: !jugo
                                ? 'var(--text-muted)'
                                : pts >= 10
                                  ? 'var(--series-4)'
                                  : pts === 0
                                    ? 'var(--text-secondary)'
                                    : 'var(--text-primary)',
                            }}
                            title={
                              jugo
                                ? pts >= 10
                                  ? `${pts} puntos en un solo cuarto`
                                  : undefined
                                : 'No jugó este periodo'
                            }
                          >
                            {jugo ? pts : '·'}
                          </td>
                        )
                      })}
                      <td className="tabular py-2 pr-3 text-right font-medium">{p.pts}</td>
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

      {/* La distinción entre `·` y `0` es la información, no un adorno: sin
          leyenda, un `·` parece un dato que falta cuando lo que dice es que el
          jugador no pisó la pista ese cuarto. */}
      {vista === 'cuartos' && (
        <p className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          <strong>0</strong> = jugó ese cuarto y no anotó. <strong>·</strong> = no jugó
          ese cuarto. En <span style={{ color: 'var(--series-4)' }}>ámbar</span>, los
          cuartos de diez puntos o más. Los minutos de la primera columna son los del
          partido entero.
        </p>
      )}
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

  // Los periodos que se jugaron, con la etiqueta con la que se leen. Se sacan
  // del box por jugador y no del marcador de equipo porque son dos cargas
  // independientes: hay 3 partidos sin resumen de equipo cuyo desglose por
  // jugador sí existe, y al revés no ocurre.
  const numerosPeriodo = [
    ...new Set(
      data.home.players
        .concat(data.away.players)
        .flatMap((p) => Object.keys(p.points_by_period).map(Number)),
    ),
  ].sort((a, b) => a - b)

  let prorroga = 0
  const periodos = numerosPeriodo.map((numero) => ({
    numero,
    etiqueta: numero <= 4 ? String(numero) : `P${++prorroga}`,
  }))
  const hayCuartos = periodos.length > 0

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
          {/* El récord con el que LLEGABA, sin contar este partido. Es lo que
              convierte un resultado en una historia: "ganó por 20" dice poco;
              "el 9-11 ganó por 20 al 13-7" lo dice todo. */}
          {t.wins_before !== null && t.losses_before !== null && (
            <span title="Récord antes de este partido">
              {t.wins_before}-{t.losses_before}
              {' · '}
            </span>
          )}
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
          {data.arena_name && <span>{data.arena_name}</span>}
          {data.attendance && <span>{data.attendance.toLocaleString('es-ES')} espectadores</span>}
          {data.officials.length > 0 && (
            <span>Árbitros: {data.officials.map((o) => o.name).join(', ')}</span>
          )}
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <Marcador t={visitante} ganador={Boolean(visitante.won)} />
          <span className="text-center text-sm" style={{ color: 'var(--text-muted)' }}>
            @
          </span>
          <Marcador t={local} ganador={Boolean(local.won)} />
        </div>

        <MarcadorPorCuartos data={data} />
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
          {/* "Por cuartos" solo aparece si hay datos por cuarto de este
              partido: un botón que lleva a una tabla vacía es peor que no
              tenerlo. */}
          {(['basicas', 'avanzadas', ...(hayCuartos ? (['cuartos'] as const) : [])] as const).map(
            (v) => (
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
                {v === 'basicas' ? 'Básicas' : v === 'avanzadas' ? 'Avanzadas' : 'Por cuartos'}
              </button>
            ),
          )}
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
          <BoxScore equipo={t} vista={vista} periodos={periodos} />
        </Card>
      ))}

      <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
        {data.periods.length === 0 && (
          <>
            La NBA no publica el resumen de este partido, así que falta el marcador por
            cuartos de equipo, la asistencia y los árbitros. Es un hueco de la fuente, no
            de la carga: son 3 partidos de 6.602. El desglose por cuarto de cada jugador
            sí está, porque viene de otro sitio.{' '}
          </>
        )}
        El desglose por cuarto llega hasta aquí: hay puntos por cuarto de cada jugador —y
        rebotes, asistencias y minutos en la ficha del jugador—, pero <strong>no</strong>{' '}
        la secuencia de anotación, ni las rachas, ni los datos de tiro por zona. Eso
        requeriría cargar el play-by-play, documentado en CAPABILITIES.md §5 con su coste.
      </p>
    </div>
  )
}
