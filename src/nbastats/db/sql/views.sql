-- Vistas materializadas: la capa analítica.
--
-- Nota de diseño: el plan preveía una `mv_player_rolling` con medias móviles de
-- 5/10/25 partidos precalculadas. Se ha sustituido por `mv_player_game_rates`,
-- una vista por jugador-partido con las tasas ya normalizadas. El motivo es que
-- materializar 3 ventanas × ~15 estadísticas por fila multiplica el tamaño por
-- 45 columnas que casi nunca se leen y obliga a refrescar todo en cada ingesta,
-- mientras que calcular la media móvil de los ~350 partidos de UN jugador en
-- Python es instantáneo. Las ventanas se calculan al vuelo en `analysis/trends.py`.

DROP MATERIALIZED VIEW IF EXISTS mv_league_season_baselines CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_player_season CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_player_game_rates CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_team_game_rates CASCADE;


-- =========================================================================
-- 1. mv_player_game_rates — la vista de trabajo
--
-- Una fila por jugador y partido, con las tasas normalizadas y todas las
-- dimensiones de split ya resueltas. De aquí leen las tendencias, los splits
-- y el game log de la API.
-- =========================================================================
CREATE MATERIALIZED VIEW mv_player_game_rates AS
SELECT
    pgs.game_id,
    pgs.player_id,
    pgs.team_id,
    g.season_id,
    g.season_type,
    g.game_date_local,

    -- Dimensiones de split. ISODOW: 1 = lunes ... 7 = domingo.
    -- Se deriva de game_date_local (hora del estadio), nunca de UTC.
    EXTRACT(ISODOW FROM g.game_date_local)::smallint AS day_of_week,
    EXTRACT(MONTH FROM g.game_date_local)::smallint  AS month,
    tgs.is_home,
    tgs.opponent_team_id,
    tgs.rest_days,
    tgs.is_back_to_back,
    tgs.won,
    pgs.started,

    -- Partido en sede neutral (París, Ciudad de México, Las Vegas). El split
    -- local/visitante debe FILTRARLOS: ahí no hay ventaja de campo, así que
    -- contarlos como "local" mete ruido en las dos direcciones a la vez.
    g.is_neutral_site,

    -- Edad fraccionaria el día del partido, para las curvas de edad.
    ((g.game_date_local - p.birthdate) / 365.25)::numeric(5,2) AS age_at_game,

    -- Totales del partido
    pgs.seconds_played,
    pgs.pts, pgs.reb, pgs.oreb, pgs.dreb, pgs.ast, pgs.stl, pgs.blk,
    pgs.tov, pgs.pf, pgs.fgm, pgs.fga, pgs.fg3m, pgs.fg3a, pgs.ftm, pgs.fta,
    pgs.plus_minus,

    -- Tasas per-36 (2160 segundos).
    -- NULLIF deja NULL los DNP en lugar de 0: un partido sin jugar no es un
    -- partido con 0 puntos per-36, es un partido sin dato. Meter ceros aquí
    -- hundiría cualquier promedio posterior.
    (pgs.pts  * 2160.0 / NULLIF(pgs.seconds_played, 0))::numeric(7,3) AS pts_per_36,
    (pgs.reb  * 2160.0 / NULLIF(pgs.seconds_played, 0))::numeric(7,3) AS reb_per_36,
    (pgs.ast  * 2160.0 / NULLIF(pgs.seconds_played, 0))::numeric(7,3) AS ast_per_36,
    (pgs.stl  * 2160.0 / NULLIF(pgs.seconds_played, 0))::numeric(7,3) AS stl_per_36,
    (pgs.blk  * 2160.0 / NULLIF(pgs.seconds_played, 0))::numeric(7,3) AS blk_per_36,
    (pgs.tov  * 2160.0 / NULLIF(pgs.seconds_played, 0))::numeric(7,3) AS tov_per_36,
    (pgs.fga  * 2160.0 / NULLIF(pgs.seconds_played, 0))::numeric(7,3) AS fga_per_36,
    -- El triple por 36 minutos separa la DECISIÓN de tirar del acierto, y es de
    -- lo más estable que tiene un jugador: el volumen se hereda mucho antes que
    -- el porcentaje.
    (pgs.fg3m * 2160.0 / NULLIF(pgs.seconds_played, 0))::numeric(7,3) AS fg3m_per_36,
    (pgs.fg3a * 2160.0 / NULLIF(pgs.seconds_played, 0))::numeric(7,3) AS fg3a_per_36,

    -- Eficiencia (de la tabla de avanzadas; LEFT JOIN, puede faltar).
    pga.ts_pct, pga.efg_pct, pga.usg_pct, pga.ast_pct, pga.reb_pct,
    pga.off_rating, pga.def_rating, pga.net_rating, pga.pie,

    -- Game Score de Hollinger: resumen del partido en una cifra.
    (pgs.pts
        + 0.4 * pgs.fgm
        - 0.7 * pgs.fga
        - 0.4 * (pgs.fta - pgs.ftm)
        + 0.7 * pgs.oreb
        + 0.3 * pgs.dreb
        + pgs.stl
        + 0.7 * pgs.ast
        + 0.7 * pgs.blk
        - 0.4 * pgs.pf
        - pgs.tov
    )::numeric(7,2) AS game_score

FROM player_game_stats pgs
JOIN games g            ON g.game_id  = pgs.game_id
JOIN players p          ON p.player_id = pgs.player_id
JOIN team_game_stats tgs ON tgs.game_id = pgs.game_id AND tgs.team_id = pgs.team_id
LEFT JOIN player_game_advanced pga
       ON pga.game_id = pgs.game_id AND pga.player_id = pgs.player_id
WHERE g.season_type <> 'preseason';

-- El acceso dominante es "todos los partidos de un jugador, en orden".
CREATE INDEX ix_mvpgr_player_date ON mv_player_game_rates (player_id, game_date_local);
CREATE INDEX ix_mvpgr_season      ON mv_player_game_rates (season_id, season_type);
CREATE INDEX ix_mvpgr_dow         ON mv_player_game_rates (player_id, day_of_week);
-- UNIQUE habilita REFRESH ... CONCURRENTLY (refresco sin bloquear lecturas).
CREATE UNIQUE INDEX ux_mvpgr_pk   ON mv_player_game_rates (game_id, player_id);


-- =========================================================================
-- 2. mv_player_season — agregados por jugador, temporada y equipo
--
-- Se agrupa TAMBIÉN por team_id: un jugador traspasado a mitad de temporada
-- produce dos filas. Es lo correcto — sus números con cada equipo son cosas
-- distintas — y quien quiera el total combinado agrega las dos.
-- =========================================================================
CREATE MATERIALIZED VIEW mv_player_season AS
SELECT
    player_id,
    season_id,
    season_type,
    team_id,

    -- Partidos jugados según la definición OFICIAL de la NBA: cuenta toda
    -- aparición, incluidas las de 0 minutos (un jugador que entra con el
    -- crono a cero). Hay 22 casos así en las 5 temporadas. Filtrarlos
    -- desviaba nuestros promedios de los publicados en NBA.com hasta en 0,3
    -- puntos para jugadores de rotación corta — poco, pero visible, y quien
    -- compare con la fuente oficial lo leerá como un error nuestro.
    -- La fuente solo incluye jugadores que aparecieron, así que COUNT(*) es
    -- exactamente eso.
    COUNT(*)                                        AS games_played,

    -- Partidos con minutos reales. Es el denominador correcto para cualquier
    -- tasa: un partido de 0 minutos no puede aportar un valor per-36.
    COUNT(*) FILTER (WHERE seconds_played > 0)      AS games_with_minutes,

    COUNT(*) FILTER (WHERE started)                 AS games_started,
    SUM(seconds_played)                             AS seconds_played,
    AVG(age_at_game)::numeric(5,2)                  AS avg_age,

    SUM(pts) AS pts, SUM(reb) AS reb, SUM(ast) AS ast,
    SUM(stl) AS stl, SUM(blk) AS blk, SUM(tov) AS tov,
    SUM(fgm) AS fgm, SUM(fga) AS fga,
    SUM(fg3m) AS fg3m, SUM(fg3a) AS fg3a,
    SUM(ftm) AS ftm, SUM(fta) AS fta,

    -- Promedios por partido sobre TODAS las apariciones, para que coincidan
    -- con los números oficiales (ver la nota de games_played).
    AVG(pts)::numeric(6,2)                   AS pts_per_game,
    AVG(reb)::numeric(6,2)                   AS reb_per_game,
    AVG(ast)::numeric(6,2)                   AS ast_per_game,
    (AVG(seconds_played) / 60.0)::numeric(5,2) AS min_per_game,

    -- Tasas agregadas: se calculan sobre los TOTALES, no promediando las tasas
    -- de cada partido. Promediar razones da un número distinto y equivocado —
    -- pondera igual un partido de 40 minutos que uno de 5.
    (SUM(pts) * 2160.0 / NULLIF(SUM(seconds_played), 0))::numeric(6,2) AS pts_per_36,
    (SUM(reb) * 2160.0 / NULLIF(SUM(seconds_played), 0))::numeric(6,2) AS reb_per_36,
    (SUM(ast) * 2160.0 / NULLIF(SUM(seconds_played), 0))::numeric(6,2) AS ast_per_36,

    (SUM(pts) / NULLIF(2 * (SUM(fga) + 0.44 * SUM(fta)), 0))::numeric(6,4) AS ts_pct,
    ((SUM(fgm) + 0.5 * SUM(fg3m)) / NULLIF(SUM(fga), 0))::numeric(6,4)     AS efg_pct,
    (SUM(fgm)::numeric / NULLIF(SUM(fga), 0))::numeric(6,4)                AS fg_pct,
    (SUM(fg3m)::numeric / NULLIF(SUM(fg3a), 0))::numeric(6,4)              AS fg3_pct,
    (SUM(ftm)::numeric / NULLIF(SUM(fta), 0))::numeric(6,4)                AS ft_pct,

    -- Intentos de triple por partido: distingue al tirador de volumen del
    -- eficiente con pocos tiros. Un 45% con 2 intentos y un 38% con 10 no son
    -- la misma habilidad, y el porcentaje solo no lo dice.
    (SUM(fg3a)::numeric / NULLIF(COUNT(*), 0))::numeric(5,2)               AS fg3a_per_game,
    (SUM(fg3m)::numeric / NULLIF(COUNT(*), 0))::numeric(5,2)               AS fg3m_per_game,

    AVG(game_score)::numeric(6,2) AS avg_game_score,
    SUM(plus_minus)               AS plus_minus

FROM mv_player_game_rates
GROUP BY player_id, season_id, season_type, team_id;

CREATE UNIQUE INDEX ux_mvps_pk ON mv_player_season
    (player_id, season_id, season_type, team_id);
CREATE INDEX ix_mvps_season ON mv_player_season (season_id, season_type);


-- =========================================================================
-- 3. mv_league_season_baselines — referencia de liga por temporada
--
-- Imprescindible para los z-scores. La liga anotaba mucho más en 2023-24 que
-- en 2018-19: sin normalizar por año se confunde la inflación de la liga con
-- la mejora de un jugador.
--
-- Solo entran jugadores CUALIFICADOS (>=20 partidos y >=15 min de media).
-- Incluir a todo el que pisó la pista arrastraría la media hacia abajo con
-- minutos de basura y haría que cualquier titular pareciese una estrella.
-- =========================================================================
CREATE MATERIALIZED VIEW mv_league_season_baselines AS
SELECT
    season_id,
    season_type,
    COUNT(*) AS qualified_players,

    AVG(pts_per_36)::numeric(6,3)          AS pts_per_36_mean,
    STDDEV_SAMP(pts_per_36)::numeric(6,3)  AS pts_per_36_sd,
    AVG(reb_per_36)::numeric(6,3)          AS reb_per_36_mean,
    STDDEV_SAMP(reb_per_36)::numeric(6,3)  AS reb_per_36_sd,
    AVG(ast_per_36)::numeric(6,3)          AS ast_per_36_mean,
    STDDEV_SAMP(ast_per_36)::numeric(6,3)  AS ast_per_36_sd,
    AVG(ts_pct)::numeric(6,4)              AS ts_pct_mean,
    STDDEV_SAMP(ts_pct)::numeric(6,4)      AS ts_pct_sd,
    AVG(efg_pct)::numeric(6,4)             AS efg_pct_mean,
    STDDEV_SAMP(efg_pct)::numeric(6,4)     AS efg_pct_sd,
    AVG(avg_game_score)::numeric(6,3)      AS game_score_mean,
    STDDEV_SAMP(avg_game_score)::numeric(6,3) AS game_score_sd

FROM mv_player_season
WHERE games_played >= 20
  AND seconds_played::numeric / NULLIF(games_played, 0) >= 900  -- 15 min/partido
GROUP BY season_id, season_type;

CREATE UNIQUE INDEX ux_mvlsb_pk ON mv_league_season_baselines (season_id, season_type);


-- =========================================================================
-- 4. mv_team_game_rates — la vista de trabajo de EQUIPOS
--
-- Espejo de mv_player_game_rates. Es lo que permite que `analysis/trends.py` y
-- `analysis/reliability.py` sirvan igual para equipos que para jugadores sin
-- tocar una línea: esos módulos reciben listas de números y no saben —ni les
-- importa— de dónde vienen.
--
-- La normalización aquí es per-100 POSESIONES, no per-36 minutos. Un equipo
-- siempre juega 48 minutos, así que los minutos no distinguen nada; lo que
-- varía es cuántas posesiones caben en esos 48 minutos, y eso es el ritmo.
-- Comparar puntos por partido entre 2018-19 y 2025-26 mezcla "anota mejor" con
-- "juega más rápido".
-- =========================================================================
CREATE MATERIALIZED VIEW mv_team_game_rates AS
SELECT
    tgs.game_id,
    tgs.team_id,
    g.season_id,
    g.season_type,
    g.game_date_local,

    -- Mismas dimensiones de split que la vista de jugadores.
    EXTRACT(ISODOW FROM g.game_date_local)::smallint AS day_of_week,
    EXTRACT(MONTH FROM g.game_date_local)::smallint  AS month,
    tgs.is_home,
    tgs.opponent_team_id,
    tgs.rest_days,
    tgs.is_back_to_back,
    tgs.won,
    g.is_neutral_site,
    g.game_label,
    g.game_sublabel,
    g.tipoff_utc,

    -- Totales del partido
    tgs.pts, tgs.reb, tgs.oreb, tgs.dreb, tgs.ast, tgs.stl, tgs.blk,
    tgs.tov, tgs.pf, tgs.fgm, tgs.fga, tgs.fg3m, tgs.fg3a, tgs.ftm, tgs.fta,
    tgs.plus_minus,

    -- Marcador del rival, para diferencial y análisis defensivo.
    opp.pts AS opp_pts,
    (tgs.pts - opp.pts)::smallint AS point_diff,

    -- Tasas per-100 posesiones. NULLIF evita dividir por cero en los partidos
    -- antiguos que no traen el dato de posesiones.
    (tgs.pts  * 100.0 / NULLIF(tgs.possessions, 0))::numeric(7,3) AS pts_per_100,
    (tgs.reb  * 100.0 / NULLIF(tgs.possessions, 0))::numeric(7,3) AS reb_per_100,
    (tgs.ast  * 100.0 / NULLIF(tgs.possessions, 0))::numeric(7,3) AS ast_per_100,
    (tgs.stl  * 100.0 / NULLIF(tgs.possessions, 0))::numeric(7,3) AS stl_per_100,
    (tgs.blk  * 100.0 / NULLIF(tgs.possessions, 0))::numeric(7,3) AS blk_per_100,
    (tgs.tov  * 100.0 / NULLIF(tgs.possessions, 0))::numeric(7,3) AS tov_per_100,
    (tgs.fg3a * 100.0 / NULLIF(tgs.possessions, 0))::numeric(7,3) AS fg3a_per_100,

    -- Avanzadas de equipo, tal cual las da la fuente.
    tgs.possessions, tgs.pace,
    tgs.off_rating, tgs.def_rating, tgs.net_rating,
    tgs.ts_pct, tgs.efg_pct

FROM team_game_stats tgs
JOIN games g ON g.game_id = tgs.game_id
-- Auto-join para traer el marcador del rival en el mismo partido.
JOIN team_game_stats opp
     ON opp.game_id = tgs.game_id AND opp.team_id = tgs.opponent_team_id
WHERE g.season_type <> 'preseason';

CREATE UNIQUE INDEX ux_mvtgr_pk    ON mv_team_game_rates (game_id, team_id);
CREATE INDEX ix_mvtgr_team_date    ON mv_team_game_rates (team_id, game_date_local);
CREATE INDEX ix_mvtgr_season       ON mv_team_game_rates (season_id, season_type);
CREATE INDEX ix_mvtgr_matchup      ON mv_team_game_rates (team_id, opponent_team_id);
