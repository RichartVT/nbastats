# Frontend — NBA Stats

Interfaz web de NBA Stats construida con React y TypeScript. Consume la API
FastAPI y presenta exploración, análisis estadístico y pronósticos **sin
duplicar lógica analítica en el cliente**.

La documentación del proyecto completo está en el [README raíz](../README.md).

## Stack

| | |
|---|---|
| React 19 · TypeScript | interfaz y tipos |
| Vite | servidor de desarrollo y build |
| TanStack Query | fetching, caché y estados de carga |
| React Router | enrutado |
| Recharts | gráficos |
| Tailwind CSS 4 | estilos, vía `@tailwindcss/vite` |
| oxlint | linter |

## Arquitectura

```
pages/ · components/
      |  useQuery
      v
TanStack Query          caché, reintentos, loading y error
      |
      v
src/api/client.ts       un único get<T>(), rutas relativas bajo /api
      |
      v
FastAPI                 :8000
```

**La capa estadística vive en el backend.** Tendencias, splits, fiabilidad,
curva de edad y pronóstico llegan ya calculados; el cliente los formatea y los
dibuja. En `src/` no hay motor estadístico: `lib/format.ts` da formato a
números y `lib/colors.ts` fija los colores de las series.

Los tipos de `src/api/types.ts` son **espejo manual** de los esquemas Pydantic
de la API — se mantienen alineados a mano, no se generan. El fichero lo declara
en su primera línea para que nadie asume lo contrario.

## Páginas

| Ruta | Para qué |
|---|---|
| `/` | Buscador y listado de jugadores, con filtros y orden encadenado |
| `/jugador/:id` | Ficha: promedios con puesto en la liga, últimos partidos, trayectoria y splits |
| `/equipos` | Listado de equipos |
| `/equipo/:id` | Ficha de equipo: plantilla, historial y análisis |
| `/clasificacion` | Clasificación por conferencia |
| `/partido/:id` | Ficha de partido: box score, cuartos y origen de los puntos |
| `/comparar` | Comparador de jugadores |
| `/tendencias` | Quién está al alza y en declive, con la curva de edad |
| `/pronostico` | Fuerza ajustada por rival y simulador de partido |
| `/que-se-repite` | Estabilidad: cuántos partidos necesita cada métrica para significar algo |

Más `*` → `NotFoundPage`.

## Estado y datos

Todo el estado de servidor pasa por TanStack Query. El `QueryClient` de
`App.tsx` usa `staleTime` de 5 minutos, `refetchOnWindowFocus: false` y un solo
reintento: los datos son históricos y solo cambian cuando corre la ingesta, así
que revalidarlos al volver a la pestaña sería tráfico sin información nueva.
`Loading` y `ErrorBox` viven en `components/Layout.tsx` y los comparten todas
las páginas.

Los menús y los desplegables se construyen desde el endpoint `/catalog`, no
desde constantes en el cliente. Es deliberado: si el backend deja de poder
contestar una estadística o una dimensión, desaparece de la interfaz sola, sin
que haya que acordarse de tocar dos sitios.

## Desarrollo local

Necesita la API corriendo en el puerto 8000 y la base de datos cargada; ambas
cosas están en el [README raíz](../README.md).

```bash
npm install
npm run dev        # http://localhost:5173
```

Otros comandos:

```bash
npm run lint       # oxlint
npm run build      # tsc -b && vite build
npm run preview    # sirve el build
```

`npm run lint` y `npm run build` son exactamente los dos pasos que corre el job
`frontend` de CI.

## Decisiones técnicas

**Proxy de Vite en vez de CORS.** `vite.config.ts` redirige `/api` a
`localhost:8000` quitando el prefijo. Así el cliente usa rutas relativas, las
mismas en desarrollo y en producción, y no hay que configurar CORS.

**Un solo punto de red.** Todas las peticiones pasan por `get<T>()` en
`src/api/client.ts`, que arma la URL, omite los parámetros vacíos y convierte
una respuesta no-OK en un `Error` con estado y cuerpo. Ninguna página llama a
`fetch` por su cuenta.

**Las imágenes se enlazan al CDN de la NBA**, derivadas del id, y cada
componente lleva su reserva: si el CDN falla se ve un marcador con las
iniciales, no una página rota. Ver `components/Media.tsx`.

**`lib/colors.ts` está separado de los gráficos** porque un módulo que exporta
componentes *y* constantes rompe el fast refresh de React.
