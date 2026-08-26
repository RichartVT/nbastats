-- Columnas derivadas: se calculan DESPUÉS de cargar, no durante la ingesta.
--
-- El motivo es que dependen del partido anterior del equipo, y durante la
-- ingesta ese partido puede no estar todavía en la base (o llegar corregido
-- más tarde). Calcularlas al vuelo daría resultados distintos según el orden
-- de carga; recalcularlas al final es determinista.

-- Días de descanso y back-to-back.
--
-- La partición incluye season_id para que el primer partido de cada temporada
-- quede con rest_days NULL: el descanso previo a un debut de temporada es el
-- verano entero y no significa lo mismo. Playoffs y temporada regular
-- comparten season_id a propósito, porque el parón previo a playoffs sí es
-- descanso real y afecta al rendimiento.
WITH ordenados AS (
    SELECT
        tgs.game_id,
        tgs.team_id,
        g.game_date_local,
        LAG(g.game_date_local) OVER (
            PARTITION BY tgs.team_id, g.season_id
            ORDER BY g.game_date_local, tgs.game_id
        ) AS fecha_anterior
    FROM team_game_stats tgs
    JOIN games g ON g.game_id = tgs.game_id
    WHERE g.season_type <> 'preseason'
)
UPDATE team_game_stats t
SET
    rest_days = (o.game_date_local - o.fecha_anterior) - 1,
    is_back_to_back = ((o.game_date_local - o.fecha_anterior) = 1)
FROM ordenados o
WHERE t.game_id = o.game_id
  AND t.team_id = o.team_id
  AND o.fecha_anterior IS NOT NULL;


-- Récord con el que cada equipo llegaba al partido.
--
-- Cuenta victorias y derrotas ANTERIORES, sin incluir el partido en curso: el
-- `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING` es lo que lo consigue.
-- Sin ese `1 PRECEDING` el marcador se contaría a sí mismo y todo equipo
-- llegaría a su primer partido con un 1-0.
--
-- La partición incluye season_type: para un partido de temporada regular es el
-- récord de la temporada, y para uno de playoffs es su recorrido en esos
-- playoffs. Arrastrar el récord regular a un séptimo partido de final daría un
-- "58-24" que no es con lo que se llega a ese partido.
--
-- El orden de desempate por game_id importa: dos partidos del mismo equipo el
-- mismo día no existen, pero sin desempate el orden no sería determinista y el
-- recálculo podría dar resultados distintos entre ejecuciones.
WITH acumulado AS (
    SELECT
        tgs.game_id,
        tgs.team_id,
        COUNT(*) FILTER (WHERE tgs.won) OVER ventana        AS wins_before,
        COUNT(*) FILTER (WHERE tgs.won = false) OVER ventana AS losses_before
    FROM team_game_stats tgs
    JOIN games g ON g.game_id = tgs.game_id
    WHERE g.season_type <> 'preseason'
    WINDOW ventana AS (
        PARTITION BY tgs.team_id, g.season_id, g.season_type
        ORDER BY g.game_date_local, tgs.game_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    )
)
UPDATE team_game_stats t
SET wins_before = a.wins_before,
    losses_before = a.losses_before
FROM acumulado a
WHERE t.game_id = a.game_id
  AND t.team_id = a.team_id;


-- Índice de ausencias: cuánta rotación no jugó.
--
-- POR QUÉ HAY QUE INFERIRLO. La fuente solo trae a los jugadores que
-- APARECIERON: no hay filas de DNP ni motivo. Así que "ausente" se deduce de un
-- hueco — estaba con este equipo por estas fechas y este día no tiene fila.
--
-- LA REGLA DE LOS TRASPASOS, que es lo único delicado. Un jugador cuenta para un
-- equipo entre su primera y su última aparición con él. La excepción importa:
-- si su última aparición con ese equipo es también la última de toda su
-- temporada, no se fue a ningún sitio — se lesionó — y sigue contando hasta el
-- final. Sin esa excepción, la lesión de temporada de una estrella desaparecería
-- del índice justo cuando más pesa.
--
-- Se exige `partidos >= 10` para extender hasta el final: sin ese guardarraíl,
-- un contrato de diez días que jugó dos partidos en noviembre contaría como
-- ausente los otros ochenta.
--
-- ROTACIÓN = 10+ MINUTOS DE MEDIA. Es la definición convencional, elegida por
-- serlo y no por el resultado que produce. La sensibilidad está publicada en la
-- bitácora: el recorrido va de 15 a 24 puntos porcentuales según dónde se ponga
-- el umbral, así que el número depende de la definición y conviene decirlo.
WITH apariciones AS (
    SELECT pgs.player_id, pgs.team_id, g.season_id,
           g.game_date_local AS fecha, pgs.seconds_played
    FROM player_game_stats pgs
    JOIN games g ON g.game_id = pgs.game_id
),
perfil AS (
    SELECT player_id, team_id, season_id,
           MIN(fecha) AS desde, MAX(fecha) AS hasta,
           COUNT(*) AS partidos,
           AVG(seconds_played) / 60.0 AS min_habituales
    FROM apariciones
    GROUP BY 1, 2, 3
),
ultima_liga AS (
    SELECT player_id, season_id, MAX(fecha) AS ultima
    FROM apariciones GROUP BY 1, 2
),
fin AS (
    SELECT season_id, MAX(game_date_local) AS fin FROM games GROUP BY 1
),
ventana AS (
    SELECT p.player_id, p.team_id, p.season_id, p.desde, p.min_habituales,
           CASE WHEN p.hasta = u.ultima AND p.partidos >= 10 THEN f.fin ELSE p.hasta END AS hasta
    FROM perfil p
    JOIN ultima_liga u USING (player_id, season_id)
    JOIN fin f USING (season_id)
    WHERE p.min_habituales >= 10
),
candidatos AS (
    SELECT tgs.game_id, tgs.team_id, v.player_id, v.min_habituales
    FROM team_game_stats tgs
    JOIN games g ON g.game_id = tgs.game_id
    JOIN ventana v
      ON v.team_id = tgs.team_id
     AND v.season_id = g.season_id
     AND g.game_date_local BETWEEN v.desde AND v.hasta
),
ausentes AS (
    SELECT c.game_id, c.team_id,
           SUM(c.min_habituales) AS minutos,
           COUNT(*) AS jugadores
    FROM candidatos c
    LEFT JOIN player_game_stats p
           ON p.game_id = c.game_id AND p.player_id = c.player_id
    WHERE p.player_id IS NULL
    GROUP BY 1, 2
)
UPDATE team_game_stats t
SET absent_minutes = COALESCE(a.minutos, 0),
    absent_players = COALESCE(a.jugadores, 0)
FROM (
    SELECT tgs.game_id, tgs.team_id, au.minutos, au.jugadores
    FROM team_game_stats tgs
    LEFT JOIN ausentes au ON au.game_id = tgs.game_id AND au.team_id = tgs.team_id
) a
WHERE t.game_id = a.game_id AND t.team_id = a.team_id;
