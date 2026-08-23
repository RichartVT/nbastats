import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Card, ErrorBox, Loading } from '../components/Layout'

export function SearchPage() {
  const [texto, setTexto] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['players', texto],
    queryFn: () => api.searchPlayers(texto, 30),
    // Se mantiene el resultado anterior mientras llega el nuevo, en lugar de
    // vaciar la lista: evita el parpadeo de esqueleto en cada tecla.
    placeholderData: (prev) => prev,
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Buscar jugador</h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
          Temporadas 2021-22 a 2025-26. La búsqueda ignora acentos: «Jokic»
          encuentra a Nikola Jokić.
        </p>
      </div>

      <input
        autoFocus
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        placeholder="Nombre del jugador…"
        className="w-full max-w-md rounded-lg px-3.5 py-2.5 text-sm outline-none"
        style={{
          background: 'var(--surface-1)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border)',
        }}
      />

      {error ? (
        <ErrorBox error={error} />
      ) : isLoading && !data ? (
        <Loading />
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left" style={{ color: 'var(--text-secondary)' }}>
                  <th className="py-2 pr-4 font-medium">Jugador</th>
                  <th className="py-2 pr-4 text-right font-medium">Partidos</th>
                  <th className="py-2 pr-4 font-medium">Temporadas</th>
                </tr>
              </thead>
              <tbody>
                {(data ?? []).map((p) => (
                  <tr key={p.player_id} style={{ borderTop: '1px solid var(--border)' }}>
                    <td className="py-2 pr-4">
                      <Link
                        to={`/jugador/${p.player_id}`}
                        className="font-medium hover:underline"
                        style={{ color: 'var(--series-1)' }}
                      >
                        {p.full_name}
                      </Link>
                    </td>
                    <td className="tabular py-2 pr-4 text-right">{p.partidos}</td>
                    <td className="py-2 pr-4" style={{ color: 'var(--text-secondary)' }}>
                      {p.primera === p.ultima ? p.primera : `${p.primera} – ${p.ultima}`}
                    </td>
                  </tr>
                ))}
                {data?.length === 0 && (
                  <tr>
                    <td colSpan={3} className="py-6 text-center" style={{ color: 'var(--text-muted)' }}>
                      Sin resultados para «{texto}».
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
