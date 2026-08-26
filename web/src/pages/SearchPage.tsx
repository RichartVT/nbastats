import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { PlayerListItem } from '../api/types'
import { Card, ErrorBox, Loading, Select } from '../components/Layout'
import { PlayerPhoto, StatusBadge, TeamLogo } from '../components/Media'
import { fmt, fmtPct } from '../lib/format'

const PAGINA = 50
const SALTO = 100

// Mismo tope que el backend. Con cuatro criterios ya se han agotado los
// empates reales; el quinto no movería ninguna fila.
const MAX_CRITERIOS = 4

const TODOS = { value: '', label: 'Todos' }

/** Los promedios ordenan mal sin un suelo de partidos: quien jugó dos y anotó
 *  20 en uno encabeza la lista de anotadores. No se impone el mínimo por la
 *  fuerza —esconder jugadores sin avisar es peor— pero sí se avisa. */
const ORDENES_POR_PROMEDIO = new Set(['puntos', 'rebotes', 'asistencias', 'minutos', 'ts'])

type Criterio = { clave: string; dir: 'asc' | 'desc' }

/**
 * "edad:desc,puntos:asc" -> criterios. Las claves repetidas se descartan:
 * volver a ordenar por algo ya ordenado no puede mover ninguna fila.
 *
 * La lista VACÍA es un estado legítimo y distinto de "ordenado por partidos".
 * El backend, sin criterios, lista por partidos — pero eso es su valor por
 * defecto, no una elección del usuario, y por eso no se marca ninguna columna.
 * Cuando esto devolvía [partidos:desc] para una URL sin orden, la cabecera PJ
 * salía siempre con flecha y su tercer clic no podía quitarla: volvía al
 * "defecto", que era ella misma.
 */
function leerOrden(texto: string): Criterio[] {
  const salida: Criterio[] = []
  for (const trozo of texto.split(',')) {
    const [clave, d] = trozo.trim().split(':')
    if (!clave || salida.some((c) => c.clave === clave)) continue
    salida.push({ clave, dir: d === 'asc' ? 'asc' : 'desc' })
  }
  return salida.slice(0, MAX_CRITERIOS)
}

const escribirOrden = (criterios: Criterio[]) =>
  criterios.map((c) => `${c.clave}:${c.dir}`).join(',')

const girar = (d: 'asc' | 'desc') => (d === 'asc' ? 'desc' : 'asc')

export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const [limite, setLimite] = useState(PAGINA)

  const q = params.get('q') ?? ''
  const estado = params.get('estado') ?? ''
  const equipo = params.get('equipo') ?? ''
  const puesto = params.get('puesto') ?? ''
  const temporada = params.get('temporada') ?? ''
  const minPartidos = params.get('min') ?? ''
  const pais = params.get('pais') ?? ''
  const minTriples = params.get('min3') ?? ''
  const minTiros = params.get('mintsa') ?? ''
  const criterios = leerOrden(params.get('orden') ?? '')

  // Los filtros viven en la URL para que un listado concreto —"pívots franceses
  // por edad y luego por rebotes"— se pueda compartir y volver a él con atrás.
  const filtrar = (cambios: Record<string, string>, rebobinar = true) => {
    const p = new URLSearchParams(params)
    for (const [clave, valor] of Object.entries(cambios)) {
      if (valor) p.set(clave, valor)
      else p.delete(clave)
    }
    setParams(p, { replace: true })
    // Filtrar cambia CUÁNTOS jugadores hay, así que volver a la primera página
    // es lo correcto. Ordenar no: quien ha desplegado los 1.030 y pulsa una
    // cabecera quiere verlos ordenados, no quedarse otra vez con 50.
    if (rebobinar) setLimite(PAGINA)
  }

  const ponerOrden = (nuevos: Criterio[]) =>
    filtrar({ orden: nuevos.length ? escribirOrden(nuevos) : '' }, false)

  /**
   * Ciclo de TRES estados por columna: mayor a menor -> menor a mayor -> sin
   * orden. El tercer clic quita el criterio en vez de volver a la primera
   * dirección; si no, una columna pulsada por curiosidad se queda pegada al
   * orden y solo se sale de ella ordenando por otra cosa.
   *
   * Una columna que YA está en la cadena avanza en su ciclo sin tocar a las
   * demás, se pulse con Mayús o sin él: girar el sentido del criterio
   * principal no es motivo para tirar los desempates que se hayan montado.
   * El modificador solo decide qué pasa con una columna NUEVA: sustituye a
   * todo (clic normal) o se añade al final (Mayús+clic).
   */
  const ordenarPor = (clave: string, aditivo: boolean) => {
    const i = criterios.findIndex((c) => c.clave === clave)

    if (i >= 0) {
      const gira = criterios[i].dir === 'desc'
      ponerOrden(
        gira
          ? criterios.map((c, j) => (j === i ? { ...c, dir: girar(c.dir) } : c))
          : criterios.filter((c) => c.clave !== clave),
      )
      return
    }

    ponerOrden(
      aditivo
        ? [...criterios, { clave, dir: 'desc' as const }].slice(0, MAX_CRITERIOS)
        : [{ clave, dir: 'desc' }],
    )
  }

  const hayFiltros = Boolean(
    q || estado || equipo || puesto || temporada || minPartidos || pais || minTriples || minTiros,
  )

  const catalogo = useQuery({ queryKey: ['catalog'], queryFn: api.catalog })
  const equipos = useQuery({ queryKey: ['teams'], queryFn: () => api.teams() })

  const orden = escribirOrden(criterios)
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: [
      'players', q, estado, equipo, puesto, temporada, minPartidos, pais, minTriples,
      minTiros, orden, limite,
    ],
    queryFn: () =>
      api.players({
        search: q,
        status: estado || undefined,
        team_id: equipo ? Number(equipo) : undefined,
        position: puesto || undefined,
        season: temporada || undefined,
        min_games: minPartidos ? Number(minPartidos) : undefined,
        country: pais || undefined,
        min_fg3a: minTriples !== '' ? Number(minTriples) : undefined,
        min_tsa: minTiros !== '' ? Number(minTiros) : undefined,
        sort: orden,
        limit: limite,
      }),
    // Se mantiene el resultado anterior mientras llega el nuevo, en lugar de
    // vaciar la lista: evita el parpadeo de esqueleto en cada tecla.
    placeholderData: (prev) => prev,
  })

  const filtros = catalogo.data?.player_filters
  const etiquetaOrden = (clave: string) =>
    filtros?.sorts.find((s) => s.value === clave)?.label ?? clave

  const opcionesEquipo = [
    TODOS,
    ...(equipos.data ?? [])
      .slice()
      .sort((a, b) => a.full_name.localeCompare(b.full_name))
      .map((t) => ({ value: String(t.team_id), label: t.full_name })),
  ]

  // Ausente en la URL no es cero: es "que decida la API". Esta es la misma
  // regla que aplica el backend, replicada aquí solo para que el desplegable
  // enseñe el suelo en efecto sin esperar a la respuesta y dar un salto.
  const suelo = (clave: string, auto: number, elegido: string) => {
    const enOrden = criterios.some((c) => c.clave === clave)
    return {
      valor: elegido !== '' ? Number(elegido) : enOrden ? auto : 0,
      automatico: elegido === '' && enOrden,
      auto,
      enOrden,
    }
  }
  const s3 = suelo('triples', filtros?.min_fg3a_auto ?? 200, minTriples)
  const sTs = suelo('ts', filtros?.min_tsa_auto ?? 500, minTiros)

  const alcance = temporada ? `en ${temporada}` : 'en las 5 temporadas cargadas'
  const avisarMinimo =
    criterios.length > 0 && ORDENES_POR_PROMEDIO.has(criterios[0].clave) && !minPartidos

  const columna = (clave: string) => {
    const i = criterios.findIndex((c) => c.clave === clave)
    return {
      clave,
      dir: i >= 0 ? criterios[i].dir : ('desc' as const),
      posicion: i >= 0 ? i + 1 : 0,
      total: criterios.length,
      onSort: ordenarPor,
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Jugadores</h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
          Temporadas 2021-22 a 2025-26. La búsqueda ignora acentos: «Jokic»
          encuentra a Nikola Jokić.
        </p>
      </div>

      {/* --- Filtros --- */}
      <Card>
        <div className="space-y-3">
          <input
            autoFocus
            value={q}
            onChange={(e) => filtrar({ q: e.target.value })}
            placeholder="Nombre del jugador…"
            className="w-full max-w-md rounded-lg px-3.5 py-2.5 text-sm outline-none"
            style={{
              background: 'var(--surface-page)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border)',
            }}
          />

          <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
            <Select
              label="Situación"
              value={estado}
              onChange={(v) => filtrar({ estado: v })}
              options={[{ value: '', label: 'Todas' }, ...(filtros?.statuses ?? [])]}
            />
            <Select
              label="Equipo"
              value={equipo}
              onChange={(v) => filtrar({ equipo: v })}
              options={opcionesEquipo}
            />
            <Select
              label="Puesto"
              value={puesto}
              onChange={(v) => filtrar({ puesto: v })}
              options={[TODOS, ...(filtros?.positions ?? [])]}
            />
            <Select
              label="País"
              value={pais}
              onChange={(v) => filtrar({ pais: v })}
              options={[
                { value: '', label: 'Todos' },
                ...(filtros?.countries ?? []).map((c) => ({
                  value: c.country,
                  label: `${c.country} (${c.n})`,
                })),
              ]}
            />
            <Select
              label="Temporada"
              value={temporada}
              onChange={(v) => filtrar({ temporada: v })}
              options={[
                { value: '', label: 'Todas' },
                ...(catalogo.data?.seasons ?? []).map((s) => ({ value: s, label: s })),
              ]}
            />
            <Select
              label="Mínimo"
              value={minPartidos}
              onChange={(v) => filtrar({ min: v })}
              options={(filtros?.min_games ?? []).map((o) => ({
                value: o.value ? String(o.value) : '',
                label: o.label,
              }))}
            />
            {/* "0" viaja en la URL como elección explícita: es lo que distingue
                "no filtres" de "no he dicho nada". */}
            <Select
              label="Triples"
              value={String(s3.valor)}
              onChange={(v) => filtrar({ min3: v })}
              options={(filtros?.min_fg3a ?? []).map((o) => ({
                value: String(o.value),
                label: o.value === s3.auto && s3.enOrden ? `${o.label} (auto)` : o.label,
              }))}
            />
            <Select
              label="Tiros"
              value={String(sTs.valor)}
              onChange={(v) => filtrar({ mintsa: v })}
              options={(filtros?.min_tsa ?? []).map((o) => ({
                value: String(o.value),
                label: o.value === sTs.auto && sTs.enOrden ? `${o.label} (auto)` : o.label,
              }))}
            />
            {hayFiltros && (
              <button
                onClick={() => {
                  const p = new URLSearchParams()
                  // El orden no es un filtro: quitar los filtros no debería
                  // reordenar la tabla bajo los pies de quien lo pulsa.
                  if (params.get('orden')) p.set('orden', params.get('orden') as string)
                  setParams(p, { replace: true })
                  setLimite(PAGINA)
                }}
                className="text-xs underline"
                style={{ color: 'var(--text-secondary)' }}
              >
                Quitar filtros
              </button>
            )}
          </div>

          {/* --- Cadena de orden --- */}
          <CadenaOrden
            criterios={criterios}
            etiqueta={etiquetaOrden}
            onQuitar={(clave) => ponerOrden(criterios.filter((c) => c.clave !== clave))}
            onLimpiar={() => ponerOrden([])}
          />

          {/* El filtro de equipo mira el equipo ACTUAL. Para quien ya no está en
              plantilla eso es su último equipo conocido, así que la lista
              incluye exjugadores: mejor decirlo que dejar que sorprenda. */}
          {equipo && (
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              El filtro de equipo usa el equipo actual, o el último conocido para
              quien ya no está en plantilla: por eso aparecen también exjugadores.
            </p>
          )}
          {pais && (
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              País de la ficha oficial de la NBA, que es el de origen del jugador
              y no siempre coincide con la selección a la que representa.
            </p>
          )}
          {avisarMinimo && (
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Ordenando por promedio sin mínimo de partidos: quien solo jugó dos
              encuentros puede encabezar la lista. Pon un mínimo para comparar
              muestras equiparables.
            </p>
          )}
          {s3.automatico && (
            <AvisoSuelo
              texto={`Ordenando por % de triples: se aplica un suelo de ${s3.auto} triples lanzados.`}
              onQuitar={() => filtrar({ min3: '0' })}
            />
          )}
          {sTs.automatico && (
            <AvisoSuelo
              texto={`Ordenando por TS%: se aplica un suelo de ${sTs.auto} intentos de tiro.`}
              onQuitar={() => filtrar({ mintsa: '0' })}
            />
          )}
        </div>
      </Card>

      {error ? (
        <ErrorBox error={error} />
      ) : isLoading && !data ? (
        <Loading />
      ) : (
        <Card
          title={data ? `${data.total} jugador${data.total === 1 ? '' : 'es'}` : 'Jugadores'}
          subtitle={
            `Partidos y promedios de temporada regular ${alcance}. ` +
            (criterios.length === 0 ? 'Sin orden elegido: se listan por partidos jugados. ' : '') +
            'Pulsa una columna para ordenar (mayor, menor, sin orden) y Mayús+clic ' +
            'para encadenar otra como desempate; el orden se calcula sobre todos los ' +
            'jugadores que cumplen los filtros, no solo sobre los visibles.'
          }
          right={
            isFetching ? (
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                Actualizando…
              </span>
            ) : undefined
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: 'var(--text-secondary)' }}>
                  <Th {...columna('nombre')} etiqueta="Jugador" align="left" />
                  <Th {...columna('edad')} etiqueta="Edad" />
                  <Th {...columna('altura')} etiqueta="ALT" ayuda="Altura en metros" />
                  <th className="py-2 pr-4 text-left font-medium">Situación</th>
                  <th className="py-2 pr-4 text-left font-medium">Equipo</th>
                  <Th
                    {...columna('partidos')}
                    etiqueta="PJ"
                    align="center"
                    ayuda="Partidos de temporada regular; el sufijo son los de playoffs y play-in"
                  />
                  <Th {...columna('minutos')} etiqueta="MIN" ayuda="Minutos por partido" />
                  <Th {...columna('puntos')} etiqueta="PTS" ayuda="Puntos por partido" />
                  <Th {...columna('rebotes')} etiqueta="REB" ayuda="Rebotes por partido" />
                  <Th {...columna('asistencias')} etiqueta="AST" ayuda="Asistencias por partido" />
                  <Th
                    {...columna('triples')}
                    etiqueta="3P%"
                    ayuda="Porcentaje de triples, con los intentos totales debajo"
                  />
                  <Th
                    {...columna('ts')}
                    etiqueta="TS%"
                    ayuda="True Shooting %, con los intentos de tiro debajo"
                  />
                  <th className="py-2 text-left font-medium">Trayectoria</th>
                </tr>
              </thead>
              <tbody>
                {(data?.items ?? []).map((p) => (
                  <Fila key={p.player_id} p={p} />
                ))}
                {data?.items.length === 0 && (
                  <tr>
                    <td
                      colSpan={13}
                      className="py-8 text-center"
                      style={{ color: 'var(--text-muted)' }}
                    >
                      Ningún jugador cumple estos filtros
                      {q ? ` y contiene «${q}»` : ''}.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {data && data.total > data.shown && (
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                Mostrando {data.shown} de {data.total}.
              </span>
              <BotonMas
                onClick={() => setLimite((n) => n + SALTO)}
                texto={`Mostrar ${Math.min(SALTO, data.total - data.shown)} más`}
              />
              <BotonMas
                onClick={() => setLimite(data.total)}
                texto={`Mostrar los ${data.total}`}
              />
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

/**
 * La cadena de orden, visible y editable.
 *
 * Sin esto, encadenar criterios sería un gesto oculto (Mayús+clic) con un
 * resultado que no se puede ni ver ni deshacer: dos flechas en dos cabeceras
 * no dicen cuál manda sobre cuál.
 */
function CadenaOrden({
  criterios,
  etiqueta,
  onQuitar,
  onLimpiar,
}: {
  criterios: Criterio[]
  etiqueta: (clave: string) => string
  onQuitar: (clave: string) => void
  onLimpiar: () => void
}) {
  if (criterios.length < 2) return null

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
        Orden:
      </span>
      {criterios.map((c, i) => (
        <span
          key={c.clave}
          className="inline-flex items-center gap-1.5 rounded-full py-1 pl-2.5 pr-1.5 text-xs"
          style={{ background: 'var(--surface-page)', border: '1px solid var(--border)' }}
        >
          <span style={{ color: 'var(--text-muted)' }}>{i + 1}</span>
          {etiqueta(c.clave)}
          <span aria-hidden style={{ color: 'var(--series-1)' }}>
            {c.dir === 'asc' ? '▲' : '▼'}
          </span>
          <button
            onClick={() => onQuitar(c.clave)}
            aria-label={`Quitar ${etiqueta(c.clave)} del orden`}
            className="px-1"
            style={{ color: 'var(--text-muted)' }}
          >
            ✕
          </button>
        </span>
      ))}
      <button onClick={onLimpiar} className="text-xs underline" style={{ color: 'var(--text-secondary)' }}>
        Quitar orden
      </button>
    </div>
  )
}

/**
 * Un suelo que se aplica solo tiene que decirse, y tiene que poder quitarse.
 * Filtrar en silencio deja al usuario mirando una lista recortada sin saber
 * por qué falta gente — que es peor que la lista con ruido.
 */
function AvisoSuelo({ texto, onQuitar }: { texto: string; onQuitar: () => void }) {
  return (
    <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
      {texto} Sin él, arriba sale quien acertó su único intento: el porcentaje es
      correcto y el puesto no significa nada, porque la precisión de un porcentaje
      depende de cuántos intentos hay detrás.{' '}
      <button onClick={onQuitar} className="underline" style={{ color: 'var(--series-1)' }}>
        Quitar el suelo
      </button>
      .
    </p>
  )
}

function BotonMas({ onClick, texto }: { onClick: () => void; texto: string }) {
  return (
    <button
      onClick={onClick}
      className="rounded-md px-3 py-1.5 text-xs"
      style={{
        background: 'var(--surface-page)',
        border: '1px solid var(--border)',
        color: 'var(--text-primary)',
      }}
    >
      {texto}
    </button>
  )
}

/**
 * Encabezado que ordena al pulsarlo.
 *
 * La flecha se pinta SIEMPRE, transparente cuando la columna no participa en
 * el orden. Si apareciera y desapareciera, cada cambio movería el ancho de la
 * columna y la tabla entera daría un salto lateral.
 */
function Th({
  etiqueta,
  clave,
  dir,
  posicion,
  total,
  onSort,
  align = 'right',
  ayuda,
}: {
  etiqueta: string
  clave: string
  dir: 'asc' | 'desc'
  posicion: number
  total: number
  onSort: (clave: string, aditivo: boolean) => void
  align?: 'left' | 'right' | 'center'
  ayuda?: string
}) {
  const activa = posicion > 0
  const justify =
    align === 'left' ? 'justify-start' : align === 'center' ? 'justify-center' : 'justify-end'

  const pista = [
    ayuda,
    activa && posicion > 1 ? `Criterio ${posicion} de ${total}` : null,
    'Pulsa para ordenar, Mayús+clic para encadenar',
  ]
    .filter(Boolean)
    .join('. ')

  return (
    <th
      className={`py-2 font-medium ${align === 'left' ? 'pr-4 text-left' : 'pr-3'}`}
      aria-sort={activa ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        onClick={(e) => onSort(clave, e.shiftKey)}
        title={pista}
        className={`inline-flex w-full items-center gap-1 ${justify} hover:underline`}
        style={{ color: activa ? 'var(--text-primary)' : 'inherit' }}
      >
        {etiqueta}
        <span
          aria-hidden
          className="inline-flex items-center text-[9px]"
          style={{ opacity: activa ? 1 : 0, color: 'var(--series-1)' }}
        >
          {dir === 'asc' ? '▲' : '▼'}
          {/* El número solo aparece cuando hay cadena: con un único criterio
              sería un "1" permanente que no informa de nada. */}
          {total > 1 && <span className="ml-0.5">{posicion}</span>}
        </span>
      </button>
    </th>
  )
}

function Fila({ p }: { p: PlayerListItem }) {
  const subtitulo = [p.jersey_number ? `#${p.jersey_number}` : null, p.position]
    .filter(Boolean)
    .join(' · ')

  return (
    <tr style={{ borderTop: '1px solid var(--border)' }}>
      <td className="py-2 pr-4">
        <Link to={`/jugador/${p.player_id}`} className="flex items-center gap-3 group">
          <PlayerPhoto playerId={p.player_id} name={p.full_name} size={36} />
          <span className="min-w-0">
            <span
              className="block truncate font-medium group-hover:underline"
              style={{ color: 'var(--series-1)' }}
            >
              {p.full_name}
            </span>
            {subtitulo && (
              <span className="block text-xs" style={{ color: 'var(--text-muted)' }}>
                {subtitulo}
              </span>
            )}
          </span>
        </Link>
      </td>

      <td className="tabular py-2 pr-3 text-right" style={{ color: 'var(--text-secondary)' }}>
        {p.age ? Math.floor(p.age) : '—'}
      </td>

      <td
        className="tabular py-2 pr-3 text-right"
        style={{ color: 'var(--text-secondary)' }}
        title={p.weight_kg ? `${p.weight_kg} kg` : undefined}
      >
        {p.height_cm ? (p.height_cm / 100).toFixed(2) : '—'}
      </td>

      <td className="py-2 pr-4">
        <StatusBadge status={p.status} />
      </td>

      {/* El encabezado de la columna dice "Equipo" a secas porque su
          significado cambia por fila: para quien está en plantilla es el
          actual, y para el resto el último. El title de cada celda lo aclara. */}
      <td className="py-2 pr-4">
        {p.current_team_id ? (
          <Link
            to={`/equipo/${p.current_team_id}`}
            title={`${p.status.team_label}: ${p.current_team_name}`}
            className="inline-flex items-center gap-2 hover:underline"
            style={{ color: p.status.on_roster ? 'var(--text-primary)' : 'var(--text-muted)' }}
          >
            <TeamLogo teamId={p.current_team_id} name={p.current_team_abbr ?? ''} size={20} />
            <span className="text-xs">{p.current_team_abbr}</span>
          </Link>
        ) : (
          <span
            className="text-xs"
            style={{ color: 'var(--text-muted)' }}
            title="Sin equipo conocido"
          >
            Sin equipo
          </span>
        )}
      </td>

      {/* Dos huecos de ancho fijo: los partidos y, a su derecha, los de
          postemporada. Si el sufijo empujara al número, las cifras dejarían de
          alinearse entre sí en cuanto una fila tuviera playoffs y la otra no. */}
      <td className="py-2 pr-3">
        <span className="flex items-baseline justify-center">
          <span className="tabular w-8 text-right">{p.partidos}</span>
          <span
            className="tabular w-8 pl-1 text-left text-[11px]"
            style={{ color: 'var(--text-muted)' }}
            title={
              p.partidos_post > 0
                ? `+${p.partidos_post} de playoffs y play-in, no incluidos en los promedios. Los de la NBA Cup sí cuentan: son temporada regular.`
                : undefined
            }
          >
            {p.partidos_post > 0 ? `+${p.partidos_post}` : ''}
          </span>
        </span>
      </td>

      <td className="tabular py-2 pr-3 text-right">{fmt(p.min_per_game, 1)}</td>
      <td className="tabular py-2 pr-3 text-right font-medium">{fmt(p.pts_per_game, 1)}</td>
      <td className="tabular py-2 pr-3 text-right">{fmt(p.reb_per_game, 1)}</td>
      <td className="tabular py-2 pr-3 text-right">{fmt(p.ast_per_game, 1)}</td>

      {/* El porcentaje con los intentos DEBAJO, no en un tooltip: un 45% con 2
          intentos y un 38% con 10 no son la misma habilidad, y esconder el
          volumen convierte la columna en un ranking falso de tiradores. */}
      <td
        className="tabular py-2 pr-3 text-right"
        title={
          p.fg3a
            ? `${p.fg3a} triples lanzados en total, ${fmt(p.fg3a_per_game, 1)} por partido`
            : 'Sin triples lanzados'
        }
      >
        <span className="block">{fmtPct(p.fg3_pct)}</span>
        <span className="block text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {p.fg3a ? `${p.fg3a} lanz.` : ''}
        </span>
      </td>

      <td
        className="tabular py-2 pr-3 text-right"
        title={p.tsa ? `${p.tsa} intentos de tiro verdaderos (TC + 0,44 · TL)` : undefined}
      >
        <span className="block">{fmtPct(p.ts_pct)}</span>
        <span className="block text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {p.tsa ? `${p.tsa} tiros` : ''}
        </span>
      </td>

      {/* Los equipos del ALCANCE, que no son necesariamente el de la columna
          "Equipo": filtrando por 2021-22, Giannis aparece con su equipo actual
          allí y con los Bucks aquí. Enseñar solo uno de los dos haría que la
          fila mintiera en una de las dos lecturas. */}
      <td className="py-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
        {p.primera === p.ultima ? p.primera : `${p.primera} – ${p.ultima}`}
        {p.equipos.length > 0 && (
          <span className="ml-1" style={{ color: 'var(--text-muted)' }}>
            ({p.equipos.join(', ')})
          </span>
        )}
      </td>
    </tr>
  )
}
