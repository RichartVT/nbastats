"""Tests del ORDER BY del listado de jugadores.

No tocan la base: comprueban el SQL que se genera. Es donde están los dos
errores fáciles de cometer e imposibles de ver a ojo —la edad corre al revés
que la fecha de nacimiento, y encadenar criterios no sirve de nada si el
primero no empata nunca— y donde una regresión no rompe nada: solo devuelve la
lista en otro orden sin que ningún test falle.
"""

from __future__ import annotations

import pytest

from nbastats.api.catalog import (
    MAX_CRITERIOS_ORDEN,
    PLAYER_SORT_LABELS,
    PlayerSort,
    SortDir,
    parse_sort,
)
from nbastats.api.queries import _ORDEN_JUGADORES, _orden

TODAS = list(_ORDEN_JUGADORES)


class TestDireccion:
    def test_por_defecto_desciende(self):
        assert _orden([("partidos", "desc")]).startswith("a.partidos DESC")

    def test_ascendente(self):
        assert _orden([("partidos", "asc")]).startswith("a.partidos ASC")

    @pytest.mark.parametrize("direccion", ["desc", "asc"])
    def test_los_nulos_siempre_al_final(self, direccion):
        """Un jugador sin TS% no es el peor tirador de la liga: es un jugador
        sin dato. Encabezar con él la lista ascendente lo leería como lo
        primero."""
        assert "NULLS LAST" in _orden([("ts", direccion)])

    @pytest.mark.parametrize("clave", TODAS)
    def test_desempate_estable(self, clave):
        """Sin desempate, dos jugadores con los mismos valores pueden
        intercambiarse entre peticiones y hacer que «Mostrar más» repita o se
        salte filas."""
        assert _orden([(clave, "desc")]).endswith("p.full_name, p.player_id")

    def test_sin_criterios_cae_en_partidos(self):
        assert _orden([]) == _orden([("partidos", "desc")])


class TestEdadInvertida:
    """La edad se ordena por años cumplidos, no por fecha de nacimiento.

    Son la misma información al revés: "los más veteranos" es la fecha MÁS
    ANTIGUA. Ordenar por la fecha sin invertirla devolvía a los novatos.
    """

    def test_mas_veterano_es_edad_descendente(self):
        generado = _orden([("edad", "desc")])
        assert "CURRENT_DATE" in generado
        assert generado.split("NULLS")[0].rstrip().endswith("DESC")

    def test_mas_joven_es_edad_ascendente(self):
        assert _orden([("edad", "asc")]).split("NULLS")[0].rstrip().endswith("ASC")

    def test_el_nombre_si_se_invierte(self):
        """A-Z es la lectura natural de "nombre", no Z-A: la dirección por
        defecto del listado es DESC y para el texto eso sería al revés."""
        assert _orden([("nombre", "desc")]).startswith("p.full_name ASC")

    def test_la_altura_no_se_invierte(self):
        assert _orden([("altura", "desc")]).startswith("p.height_cm DESC")


class TestCriteriosEncadenados:
    """Lo que hace que combinar criterios sirva de algo.

    Los criterios que no son el último ordenan por el valor REDONDEADO A LO QUE
    SE VE; el último, por el exacto. Sin eso, "por edad y luego por puntos" no
    movería ni una fila: la edad exacta no empata casi nunca, así que el
    segundo criterio no llegaría a aplicarse.
    """

    def test_el_criterio_intermedio_usa_el_valor_mostrado(self):
        generado = _orden([("edad", "desc"), ("puntos", "desc")])
        assert generado.startswith("FLOOR(")

    def test_el_ultimo_criterio_usa_el_valor_exacto(self):
        generado = _orden([("edad", "desc"), ("puntos", "desc")])
        assert "ROUND(" not in generado.split(",")[-3]

    def test_con_un_solo_criterio_no_se_redondea(self):
        """Ordenar solo por puntos debe dar el orden exacto, sin agrupar por el
        decimal que se enseña."""
        assert "ROUND(" not in _orden([("puntos", "desc")])

    def test_cada_criterio_aporta_su_termino(self):
        generado = _orden([("edad", "desc"), ("puntos", "asc"), ("asistencias", "desc")])
        assert generado.count("NULLS LAST") == 3

    def test_las_direcciones_son_independientes(self):
        generado = _orden([("edad", "desc"), ("puntos", "asc")])
        primero, segundo = generado.split("NULLS LAST")[:2]
        assert primero.rstrip().endswith("DESC")
        assert segundo.rstrip().endswith("ASC")

    def test_se_recorta_al_tope(self):
        de_mas = [(c, "desc") for c in TODAS]
        assert len(de_mas) > MAX_CRITERIOS_ORDEN
        assert _orden(de_mas).count("NULLS LAST") == MAX_CRITERIOS_ORDEN

    def test_una_clave_desconocida_no_rompe_el_resto(self):
        generado = _orden([("inventada", "desc"), ("puntos", "desc")])
        assert generado.count("NULLS LAST") == 1
        assert "NULLS LAST" in generado


class TestParseSort:
    def test_clave_suelta(self):
        assert parse_sort("puntos") == [("puntos", "desc")]

    def test_hereda_la_direccion_por_defecto(self):
        """Es lo que mantiene viva la forma antigua `?sort=puntos&dir=asc`."""
        assert parse_sort("puntos", "asc") == [("puntos", "asc")]

    def test_la_direccion_escrita_gana_a_la_por_defecto(self):
        assert parse_sort("puntos:desc", "asc") == [("puntos", "desc")]

    def test_cadena_completa(self):
        assert parse_sort("edad:desc,puntos:asc,asistencias:desc") == [
            ("edad", "desc"),
            ("puntos", "asc"),
            ("asistencias", "desc"),
        ]

    @pytest.mark.parametrize("entrada", ["", "   ", ",,"])
    def test_vacio_cae_en_el_orden_por_defecto(self, entrada):
        assert parse_sort(entrada) == [("partidos", "desc")]

    def test_tolera_espacios_y_mayusculas(self):
        assert parse_sort(" Edad : DESC , Puntos ") == [("edad", "desc"), ("puntos", "desc")]

    def test_las_claves_repetidas_se_descartan(self):
        """En una cadena manda la primera aparición: volver a ordenar por algo
        que ya está ordenado no puede mover ninguna fila."""
        assert parse_sort("puntos:desc,edad:asc,puntos:asc") == [
            ("puntos", "desc"),
            ("edad", "asc"),
        ]

    def test_clave_desconocida_es_error(self):
        with pytest.raises(ValueError, match="Orden desconocido"):
            parse_sort("altura_en_pies")

    def test_direccion_desconocida_es_error(self):
        with pytest.raises(ValueError, match="Dirección desconocida"):
            parse_sort("puntos:arriba")

    def test_el_error_dice_que_valores_valen(self):
        """Un 422 que solo dice "inválido" obliga a leer el código."""
        with pytest.raises(ValueError) as e:
            parse_sort("inventada")
        assert "puntos" in str(e.value)


class TestContratoConElCatalogo:
    def test_toda_clave_del_enum_tiene_expresion(self):
        """Si no, FastAPI acepta el valor y la consulta lo ignora en silencio
        devolviendo el orden por defecto."""
        assert {s.value for s in PlayerSort} == set(_ORDEN_JUGADORES)

    def test_toda_clave_del_enum_tiene_etiqueta(self):
        assert set(PLAYER_SORT_LABELS) == set(PlayerSort)

    def test_solo_hay_dos_direcciones(self):
        assert {d.value for d in SortDir} == {"asc", "desc"}

    @pytest.mark.parametrize("clave", TODAS)
    @pytest.mark.parametrize("direccion", ["asc", "desc"])
    def test_nunca_se_cuela_texto_del_cliente(self, clave, direccion):
        """El ORDER BY se monta con f-string. Lo único que lo hace seguro es
        que ni la columna ni la dirección salgan nunca de la petición: se
        resuelven contra este diccionario o se descartan."""
        generado = _orden([(clave, direccion)])
        assert generado.startswith(_ORDEN_JUGADORES[clave].exacta)
        assert ";" not in generado

    def test_una_clave_maliciosa_no_llega_al_sql(self):
        assert "DROP" not in _orden([("puntos; DROP TABLE players --", "desc")])
