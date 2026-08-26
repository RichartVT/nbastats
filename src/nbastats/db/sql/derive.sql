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
