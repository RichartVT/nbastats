import { Link } from 'react-router-dom'
import { Card } from '../components/Layout'

/**
 * Cualquier URL desconocida.
 *
 * Antes no había ruta comodín y el resultado era una página EN BLANCO: sin
 * error, sin navegación y sin forma de saber si la aplicación se había roto o
 * la dirección estaba mal.
 */
export function NotFoundPage() {
  return (
    <Card title="Aquí no hay nada">
      <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
        Esa dirección no existe. Puede que el enlace esté mal escrito, o que
        apunte a un jugador, equipo o partido que no está cargado.
      </p>
      <p className="mt-3 text-sm">
        <Link to="/" style={{ color: 'var(--series-1)' }} className="hover:underline">
          Volver a los jugadores
        </Link>
      </p>
    </Card>
  )
}
