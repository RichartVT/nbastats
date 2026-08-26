"""El método delta contra el sesgo de supervivencia.

La forma de probar esto es un mundo sintético donde la verdad se conoce: se
inventa una curva de edad, se generan jugadores, y se les aplica la MISMA regla
que aplica la NBA — al que rinde poco se le deja de fichar. Luego se comprueba
qué método recupera la curva verdadera y cuál se deja engañar.

Es el patrón del resto del proyecto: probar que un efecto REAL se detecta, y que
uno inventado no.
"""

from __future__ import annotations

import numpy as np
import pytest

from nbastats.analysis.trends import fit_age_curve, fit_delta_age_curve

# Verdad del mundo sintético: pico a los 26 y caída fuerte a partir de los 30.
PICO = 26.0
CAIDA = 0.55  # puntos por año al cuadrado


def _verdad(edad: float) -> float:
    return 20.0 - CAIDA * (edad - PICO) ** 2 / 4


def _liga(semilla: int, *, con_corte: bool, umbral: float = 12.0):
    """Genera carreras. Con `con_corte`, al que baja del umbral lo cortan."""
    rng = np.random.default_rng(semilla)
    obs = []
    for pid in range(400):
        # Cada jugador tiene su propio nivel: hay buenos y malos.
        nivel = rng.normal(0.0, 4.0)
        for edad in range(20, 40):
            valor = _verdad(edad) + nivel + rng.normal(0, 1.2)
            if con_corte and valor < umbral:
                break  # fuera de la liga, y no vuelve
            obs.append((pid, edad, valor))
    return obs


def test_sin_corte_los_dos_metodos_aciertan():
    """Control: si no hay selección, no hay sesgo que corregir."""
    obs = _liga(1, con_corte=False)
    t = fit_age_curve([o[1] for o in obs], [o[2] for o in obs])
    d = fit_delta_age_curve(obs, min_players_per_age=10, reference_age=26)
    assert abs(t.peak_age - PICO) < 1.5
    assert d is not None
    idx = dict(d.curve)
    # A los 36 la verdad son ~72% del pico. Los dos deben acercarse.
    verdad_36 = 100 * _verdad(36) / _verdad(PICO)
    assert abs(idx[36] - verdad_36) < 8, idx[36]


def test_con_corte_el_transversal_se_deja_engañar():
    """EL SESGO, reproducido: los supervivientes a los 36 son los buenos."""
    obs = _liga(2, con_corte=True)
    t = fit_age_curve([o[1] for o in obs], [o[2] for o in obs])
    verdad_36 = 100 * _verdad(36) / _verdad(PICO)
    transversal_36 = 100 * t.relative_to_peak(36)
    assert transversal_36 > verdad_36 + 5, (
        f"el transversal debería SOBREESTIMAR: da {transversal_36:.1f}% "
        f"y la verdad es {verdad_36:.1f}%"
    )


def test_con_corte_el_delta_se_acerca_mucho_mas():
    """LA PRUEBA QUE JUSTIFICA EL MÉTODO.

    Sobre los mismos datos sesgados, la curva delta tiene que quedar más cerca
    de la verdad que la transversal. No exactamente encima —el delta también
    tiene sesgo residual, porque quien se cae no aporta el paso siguiente— pero
    sí claramente más cerca.
    """
    obs = _liga(3, con_corte=True)
    t = fit_age_curve([o[1] for o in obs], [o[2] for o in obs])
    d = fit_delta_age_curve(obs, min_players_per_age=10, reference_age=26)
    assert d is not None

    idx = dict(d.curve)
    edad = max(e for e in idx if e <= 35)
    verdad = 100 * _verdad(edad) / _verdad(PICO)
    err_delta = abs(idx[edad] - verdad)
    err_trans = abs(100 * t.relative_to_peak(edad) - verdad)
    assert err_delta < err_trans, (
        f"a los {edad}: delta {idx[edad]:.1f}% (error {err_delta:.1f}) contra "
        f"transversal {100*t.relative_to_peak(edad):.1f}% (error {err_trans:.1f}), "
        f"verdad {verdad:.1f}%"
    )


def test_el_delta_sigue_subestimando_el_declive():
    """La honestidad del método: corrige mucho, no corrige todo.

    Si algún día este test empezara a fallar porque el delta ACIERTA, sería una
    buena noticia — y habría que revisar el aviso que acompaña a la curva.
    """
    obs = _liga(4, con_corte=True)
    d = fit_delta_age_curve(obs, min_players_per_age=10, reference_age=26)
    idx = dict(d.curve)
    edad = max(e for e in idx if e <= 35)
    verdad = 100 * _verdad(edad) / _verdad(PICO)
    assert idx[edad] >= verdad - 2, "no debería sobrepasar el declive real"


def test_solo_empareja_temporadas_consecutivas():
    """Un jugador que se pierde una temporada entera no aporta un salto de 2
    años como si fuera de 1: eso mezclaría dos años de envejecimiento."""
    obs = [(1, 24, 10.0), (1, 26, 6.0), (2, 24, 10.0), (2, 25, 9.0), (3, 24, 8.0), (3, 25, 7.0)]
    d = fit_delta_age_curve(obs, min_players_per_age=2, reference_age=24)
    assert d.deltas[0].n_players == 2  # el jugador 1 no cuenta
    assert d.deltas[0].mean_change == pytest.approx(-1.0)


def test_exige_muestra_minima_por_edad():
    obs = [(i, 30, 10.0) for i in range(5)] + [(i, 31, 9.0) for i in range(5)]
    assert fit_delta_age_curve(obs, min_players_per_age=20) is None
    assert fit_delta_age_curve(obs, min_players_per_age=5) is not None


def test_el_indice_vale_100_en_la_referencia():
    obs = _liga(5, con_corte=False)
    d = fit_delta_age_curve(obs, min_players_per_age=10, reference_age=27)
    assert dict(d.curve)[27] == pytest.approx(100.0)
    assert dict(d.cumulative)[27] == pytest.approx(0.0)
