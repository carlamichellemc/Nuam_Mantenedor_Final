"""Pruebas unitarias del motor de cálculo (RF5, RF6, RF7) y de las validaciones."""
from decimal import Decimal

import pytest

import core
from core import ErrorValidacion


def test_U01_factor_8_con_8_decimales_exactos():
    """RF6 · monto 400.000 sobre suma 1.000.000 -> 0,40000000"""
    assert str(core.calcular_factor(400000, 1000000)) == "0.40000000"


def test_U02_redondeo_al_octavo_decimal():
    """RF6 · 1/3 -> 0,33333333 y 2/3 -> 0,66666667 (redondeo half-up)"""
    assert str(core.calcular_factor(1, 3)) == "0.33333333"
    assert str(core.calcular_factor(2, 3)) == "0.66666667"


def test_U03_suma_8_a_19_mayor_que_1_se_rechaza():
    """RF6 · factores 8-19 que suman 1,05 -> error"""
    with pytest.raises(ErrorValidacion, match="supera 1"):
        core.validar_factores({8: "0.50", 9: "0.55"})


def test_U04_suma_exactamente_1_se_acepta():
    assert core.validar_factores({8: "0.5", 9: "0.5"})[8] == Decimal("0.5")


def test_U05_tolerancia_de_redondeo():
    """6 partes iguales dan 0,16666667 x 6 = 1,00000002: se acepta por redondeo; 1,0000001 ya no"""
    m, f = core.calcular_desde_montos({n: 1 for n in range(8, 14)})
    assert sum(f.values()) == Decimal("1.00000002")
    with pytest.raises(ErrorValidacion):
        core.validar_factores({8: "0.5", 9: "0.5000001"})


def test_U06_factores_20_a_37_no_cuentan_en_la_suma_8_19():
    """RF6 · el factor 20 (monto 100.000 sobre suma 1.000.000) no suma contra el límite de 1"""
    _, f = core.calcular_desde_montos({8: 400000, 9: 350000, 10: 250000, 20: 100000})
    assert f[20] == Decimal("0.10000000") and sum(v for n, v in f.items() if n < 20) == Decimal("1")


def test_U07_30_factores_8_al_37():
    """RF5/RF6 · se aceptan los 30 factores del 8 al 37"""
    montos = {n: (1000 if n < 20 else 10) for n in range(8, 38)}
    _, f = core.calcular_desde_montos(montos)
    assert sorted(f) == list(range(8, 38))
    assert core.NROS == range(8, 38)


def test_U08_factor_mayor_que_1_se_rechaza():
    """Un monto de las columnas 20+ mayor que la suma 8-19 da un factor > 1"""
    with pytest.raises(ErrorValidacion, match="supera 1"):
        core.calcular_desde_montos({8: 100, 20: 500})


def test_U09_suma_cero_y_montos_negativos():
    with pytest.raises(ErrorValidacion, match="mayor que cero"):
        core.calcular_desde_montos({8: 0, 9: 0})
    with pytest.raises(ErrorValidacion, match="negativo"):
        core.calcular_desde_montos({8: 100, 9: -5})
    with pytest.raises(ErrorValidacion):
        core.calcular_desde_montos({})


def test_U10_monto_cero_en_una_columna():
    _, f = core.calcular_desde_montos({8: 0, 9: 100})
    assert f"{f[8]:.8f}" == "0.00000000"


def test_U11_numero_de_factor_inexistente():
    with pytest.raises(ErrorValidacion, match="no existe"):
        core.calcular_desde_montos({7: 100})
    with pytest.raises(ErrorValidacion, match="no existe"):
        core.calcular_desde_montos({38: 100})


def test_U12_ingreso_directo_de_factores_RF7():
    _, f = core.calcular_desde_factores({"8": "0.923453", "9": "0.07"})
    assert f[8] == Decimal("0.92345300")
    with pytest.raises(ErrorValidacion, match="entre 0 y 1"):
        core.calcular_desde_factores({"8": "1.5"})
    with pytest.raises(ErrorValidacion, match="entre 0 y 1"):
        core.calcular_desde_factores({"8": "-0.1"})
    with pytest.raises(ErrorValidacion):
        core.calcular_desde_factores({})


@pytest.mark.parametrize("texto,esperado", [("1250000", "1250000"), ("1.250.000", "1250000"), ("1.250.000,50", "1250000.50"),
                                            ("0,40", "0.40"), ("1250.50", "1250.50"), ("$ 1.000", "1000")])
def test_U13_formatos_de_numero(texto, esperado):
    assert core.parsear_numero(texto) == Decimal(esperado)


@pytest.mark.parametrize("malo", ["abc", "", "1e999999999", "NaN", "12a"])
def test_U14_numeros_invalidos(malo):
    with pytest.raises(ErrorValidacion):
        core.parsear_numero(malo)


def test_U15_datos_base_validos_y_normalizados():
    b = core.validar_datos_base({"ejercicio": "2025", "mercado": "acn", "secuencia": "123", "tipo_sociedad": "a",
                                 "fecha_pago": "15-04-2025", "valor_historico": "1.250,50", "isfut": "sí"})
    assert b["mercado"] == "ACN" and b["tipo_sociedad"] == "A" and b["isfut"] is True and str(b["fecha_pago"]) == "2025-04-15"


@pytest.mark.parametrize("campo,valor", [("ejercicio", 1999), ("ejercicio", "abc"), ("mercado", "XXX"), ("secuencia", -1),
                                          ("tipo_sociedad", "Z"), ("fecha_pago", "31-02-2025"), ("valor_historico", "-5"),
                                          ("descripcion", "x" * 201), ("factor_actualizacion", "-1")])
def test_U16_datos_base_invalidos(campo, valor):
    d = {"ejercicio": 2025, "mercado": "ACN", "secuencia": 1}
    d[campo] = valor
    with pytest.raises(ErrorValidacion):
        core.validar_datos_base(d)
