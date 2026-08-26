"""Las mismas fórmulas, escritas dos veces: ¿dan lo mismo?

`analysis/rates.py` calcula per-36, TS%, eFG% y Game Score en Python. Las vistas
materializadas los calculan otra vez en SQL. **La API solo usa las de SQL**, así
que las de Python llevaban 170 líneas sin que nada garantizara que coincidieran.

En vez de borrar una de las dos, la duplicación se convierte en VERIFICACIÓN
CRUZADA: dos implementaciones independientes que tienen que estar de acuerdo. Es
el patrón del resto del proyecto — la doble ruta del modelo de probabilidad, o
los puntos en la pintura del rival contra los propios del otro equipo.

SON DOS COMPROBACIONES DISTINTAS, Y CONFUNDIRLAS COSTÓ UN RATO:

1. **Temporada**: ahí el SQL SÍ calcula la fórmula (`SUM(pts) / (2*(SUM(fga) +
   0.44*SUM(fta)))`). Es el cruce Python ↔ SQL de verdad.
2. **Partido**: ahí `ts_pct` y `efg_pct` **no los calcula nadie nuestro** —
   vienen de `player_game_advanced`, o sea de la NBA, con 3 decimales. Comparar
   ahí no cruza dos implementaciones nuestras: verifica que nuestra fórmula
   coincide con la de la liga, que es otra cosa y también vale la pena.

La primera versión del test usaba una sola tolerancia para las dos y fallaba por
exactamente 0,0005 — la mitad del último decimal de la NBA. La tolerancia no era
el problema; mezclar las dos preguntas sí.

SE SALTA SI NO HAY BASE DE DATOS. Los otros ~500 tests son puros y corren en
menos de dos segundos en cualquier máquina; romper esa propiedad por éste sería
un mal negocio.
"""

from __future__ import annotations

import pytest

from nbastats.analysis.rates import (
    effective_fg_pct,
    game_score,
    per_36,
    true_shooting_pct,
)

# Cada tolerancia es el redondeo del tipo de la columna, no un número elegido
# hasta que el test pasara. Una diferencia MAYOR es un hallazgo que hay que
# publicar, no un margen que haya que ensanchar.
TOL_NUMERIC_6_4 = 5e-5   # numeric(6,4): ts_pct, efg_pct de temporada
TOL_NUMERIC_6_2 = 5e-3   # numeric(6,2): pts_per_36 de temporada
TOL_NUMERIC_7_3 = 5e-4   # numeric(7,3): pts_per_36 y game_score de partido
TOL_FUENTE_NBA = 5e-4    # la NBA publica 3 decimales: media unidad del último


def _consulta(sql: str):
    sa = pytest.importorskip("sqlalchemy")
    try:
        from nbastats.db.session import get_sessionmaker

        with get_sessionmaker()() as s:
            return [dict(f) for f in s.execute(sa.text(sql)).mappings()]
    except Exception as e:  # noqa: BLE001 — sin base, estos tests no aplican
        pytest.skip(f"sin base de datos: {type(e).__name__}")


@pytest.fixture(scope="module")
def temporadas():
    return _consulta("""
        SELECT pts, fgm, fga, fg3m, fta, seconds_played,
               ts_pct, efg_pct, pts_per_36
        FROM mv_player_season
        WHERE season_type = 'regular' AND fga > 100
        ORDER BY player_id, season_id
        LIMIT 800
    """)


@pytest.fixture(scope="module")
def partidos():
    return _consulta("""
        SELECT pts, fgm, fga, fg3m, ftm, fta, oreb, dreb, stl, ast, blk, pf, tov,
               seconds_played, pts_per_36, ts_pct, efg_pct, game_score
        FROM mv_player_game_rates
        WHERE seconds_played > 600 AND fga > 0
        ORDER BY game_id, player_id
        LIMIT 800
    """)


def _comprueba(filas, fn, columna, tol):
    peor = 0.0
    for f in filas:
        if f[columna] is None:
            continue
        esperado = fn(f)
        if esperado is None:
            continue
        d = abs(esperado - float(f[columna]))
        peor = max(peor, d)
        assert d < tol, f"{columna}: python {esperado} vs SQL {f[columna]} · {f}"
    return peor


# --- 1) El cruce de verdad: Python contra SQL, a nivel de temporada ---------


def test_hay_muestra_suficiente(temporadas):
    assert len(temporadas) >= 500, f"solo {len(temporadas)} filas"


def test_true_shooting_temporada(temporadas):
    """El 0,44 de los tiros libres tiene que ser el mismo en los dos sitios."""
    _comprueba(
        temporadas,
        lambda f: true_shooting_pct(f["pts"], f["fga"], f["fta"]),
        "ts_pct",
        TOL_NUMERIC_6_4,
    )


def test_efg_temporada(temporadas):
    """Y el 0,5 del triple."""
    _comprueba(
        temporadas,
        lambda f: effective_fg_pct(f["fgm"], f["fg3m"], f["fga"]),
        "efg_pct",
        TOL_NUMERIC_6_4,
    )


def test_per_36_temporada(temporadas):
    _comprueba(
        temporadas,
        lambda f: per_36(f["pts"], f["seconds_played"]),
        "pts_per_36",
        TOL_NUMERIC_6_2,
    )


def test_la_desviacion_es_solo_redondeo(temporadas):
    """La diferencia MEDIA debe ser mucho menor que la tolerancia.

    Si rondara el límite, el test estaría pasando por poco y una discrepancia
    real quedaría escondida detrás del margen.
    """
    difs = [
        abs(true_shooting_pct(f["pts"], f["fga"], f["fta"]) - float(f["ts_pct"]))
        for f in temporadas
        if f["ts_pct"] is not None
    ]
    media = sum(difs) / len(difs)
    assert media < TOL_NUMERIC_6_4, f"desviación media {media:.2e}"


# --- 2) Nivel de partido -----------------------------------------------------


def test_per_36_partido(partidos):
    """Aquí sí lo calcula la vista, con `numeric(7,3)`."""
    _comprueba(
        partidos,
        lambda f: per_36(f["pts"], f["seconds_played"]),
        "pts_per_36",
        TOL_NUMERIC_7_3,
    )


def test_game_score_partido(partidos):
    """Doce coeficientes de Hollinger escritos dos veces. Si alguien toca uno en
    un sitio y no en el otro, el análisis y la pantalla discrepan en silencio."""
    _comprueba(
        partidos,
        lambda f: game_score(
            f["pts"], f["fgm"], f["fga"], f["ftm"], f["fta"], f["oreb"], f["dreb"],
            f["stl"], f["ast"], f["blk"], f["pf"], f["tov"],
        ),
        "game_score",
        TOL_NUMERIC_7_3,
    )


def test_nuestra_formula_coincide_con_la_de_la_nba(partidos):
    """A nivel de partido, `ts_pct` y `efg_pct` los publica la NBA.

    Esto no cruza dos implementaciones nuestras: comprueba que nuestra fórmula
    es la misma que la de la liga. Si un día dejara de serlo, significaría que
    la NBA cambió su definición — que ya ha pasado con otras métricas.
    """
    peor_ts = _comprueba(
        partidos,
        lambda f: true_shooting_pct(f["pts"], f["fga"], f["fta"]),
        "ts_pct",
        TOL_FUENTE_NBA + 1e-9,
    )
    peor_efg = _comprueba(
        partidos,
        lambda f: effective_fg_pct(f["fgm"], f["fg3m"], f["fga"]),
        "efg_pct",
        TOL_FUENTE_NBA + 1e-9,
    )
    # Y que la peor diferencia sea EXACTAMENTE el redondeo a 3 decimales, no
    # algo menor que casualmente cabe: confirma de dónde viene el dato.
    assert peor_ts == pytest.approx(5e-4, abs=1e-5)
    assert peor_efg == pytest.approx(5e-4, abs=1e-5)


# --- 3) Lo que se guarda tiene que corresponder con lo que el modelo cubre ----


@pytest.fixture(scope="module")
def coherencia():
    return _consulta("""
        SELECT
          (SELECT COUNT(*) FROM game_predictions p
             JOIN games g ON g.game_id = p.game_id
            WHERE g.is_neutral_site)                       AS neutrales,
          (SELECT COUNT(*) FROM game_predictions p
             JOIN games g ON g.game_id = p.game_id
            WHERE g.season_type <> 'regular')              AS no_regulares,
          (SELECT COUNT(DISTINCT fitted_at) FROM game_predictions) AS corridas
    """)


def test_no_hay_predicciones_de_partidos_que_el_modelo_excluye(coherencia):
    """FALLO REAL, encontrado corriendo `daily` entero.

    `enrich` marcó como sede neutral cuatro partidos de 2023-24 —las semifinales
    de la Copa NBA en Las Vegas, el de París y el de México— que el modelo
    excluye a propósito. Sus predicciones viejas se quedaron en la tabla, porque
    `upsert` escribe y actualiza pero no borra, y `/model/backtest` las habría
    contado con coeficientes de otra corrida.
    """
    f = coherencia[0]
    assert f["neutrales"] == 0, f"{f['neutrales']} predicciones de sedes neutrales"
    assert f["no_regulares"] == 0, "hay predicciones fuera de temporada regular"


def test_todas_las_predicciones_son_de_la_misma_corrida(coherencia):
    """Si conviven dos `fitted_at`, unas se calcularon con otros coeficientes."""
    assert coherencia[0]["corridas"] == 1
