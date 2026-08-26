/**
 * Colores de las series de los gráficos.
 *
 * Vive aquí y no junto al gráfico porque un fichero que exporta componentes
 * *y* constantes rompe el fast refresh: React no puede saber si el módulo
 * cambió por el componente o por el dato, y remonta de más.
 */
export const COLORES_SERIE = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--series-4)',
] as const
