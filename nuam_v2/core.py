"""Reglas de negocio puras del Mantenedor (sin base de datos ni web): cálculo y validación de factores."""
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

NRO_MIN, NRO_MAX = 8, 37                       # Factor 8 al Factor 37
NROS = range(NRO_MIN, NRO_MAX + 1)
NROS_SUMA = range(8, 20)                       # la suma de los factores 8 al 19 no puede superar 1
OCTAVO = Decimal("0.00000001")
TOLERANCIA = Decimal("0.00000006")             # 12 columnas x medio punto del 8.º decimal (por redondeo)
MERCADOS = ("ACN", "CFI", "FMU")               # acciones, cuotas de fondos de inversión, fondos mutuos


class ErrorValidacion(ValueError):
    """Dato o regla de negocio inválida; la API la entrega como HTTP 422."""


def parsear_numero(valor, campo="valor"):
    """Convierte texto o número en Decimal. Acepta 1250000, 1.250.000,50, 1250000.50 y 0,40."""
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return Decimal(str(valor))
    s = str(valor).strip().replace(" ", "").replace("$", "")
    if s == "":
        raise ErrorValidacion(f"{campo}: vacío")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):          # formato chileno 1.250.000,50
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:                              # 0,40
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except (InvalidOperation, ArithmeticError):
        raise ErrorValidacion(f"{campo}: '{valor}' no es un número válido")
    if not d.is_finite():
        raise ErrorValidacion(f"{campo}: '{valor}' no es un número válido")
    if d.adjusted() >= 15:
        raise ErrorValidacion(f"{campo}: el valor es demasiado grande")
    return d


def _nro(k):
    try:
        n = int(k)
    except (TypeError, ValueError):
        raise ErrorValidacion(f"Número de factor inválido: {k}")
    if n not in NROS:
        raise ErrorValidacion(f"El factor {n} no existe (los válidos son del {NRO_MIN} al {NRO_MAX})")
    return n


def calcular_factor(monto, suma_columnas):
    """factor = monto de la columna / suma de los montos de las columnas 8 a 19, redondeado al 8.º decimal."""
    monto, suma = parsear_numero(monto, "monto"), parsear_numero(suma_columnas, "suma")
    if suma <= 0:
        raise ErrorValidacion("La suma de los montos de las columnas 8 a 19 debe ser mayor que cero")
    if monto < 0:
        raise ErrorValidacion("El monto no puede ser negativo")
    return (monto / suma).quantize(OCTAVO, rounding=ROUND_HALF_UP)


def validar_factores(factores):
    """Valida factores ingresados o calculados: cada uno entre 0 y 1 con 8 decimales, y suma 8-19 <= 1."""
    out = {}
    for k, v in factores.items():
        n = _nro(k)
        f = parsear_numero(v, f"Factor {n}").quantize(OCTAVO, rounding=ROUND_HALF_UP)
        if f < 0 or f > 1:
            raise ErrorValidacion(f"El factor {n} debe estar entre 0 y 1 (valor {f})")
        out[n] = f
    suma = sum((f for n, f in out.items() if n in NROS_SUMA), Decimal(0))
    if suma > 1 + TOLERANCIA:
        raise ErrorValidacion(f"La suma de los factores 8 al 19 es {suma} y supera 1")
    return out


def calcular_desde_montos(montos):
    """montos: {nro: monto}. Devuelve ({nro: monto Decimal}, {nro: factor Decimal})."""
    m = {}
    for k, v in montos.items():
        if v is None or str(v).strip() == "":
            continue
        n = _nro(k)
        d = parsear_numero(v, f"Monto columna {n}")
        if d < 0:
            raise ErrorValidacion(f"El monto de la columna {n} no puede ser negativo")
        m[n] = d
    if not m:
        raise ErrorValidacion("Ingrese al menos un monto")
    suma = sum((d for n, d in m.items() if n in NROS_SUMA), Decimal(0))
    factores = {n: calcular_factor(d, suma) for n, d in m.items()}
    for n, f in factores.items():
        if f > 1:
            raise ErrorValidacion(f"El factor {n} da {f}, que supera 1: el monto de la columna {n} es mayor que la suma de las columnas 8 a 19")
    return m, validar_factores(factores)


def calcular_desde_factores(factores):
    """Ingreso directo de factores. Devuelve ({}, {nro: factor})."""
    if not factores:
        raise ErrorValidacion("Ingrese al menos un factor")
    return {}, validar_factores({k: v for k, v in factores.items() if v is not None and str(v).strip() != ""})


def parsear_fecha(valor, campo="fecha"):
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ErrorValidacion(f"{campo}: '{valor}' no es una fecha válida (use DD-MM-AAAA)")


def _entero(valor, campo, minimo=0, maximo=None, obligatorio=True):
    if valor is None or str(valor).strip() == "":
        if obligatorio:
            raise ErrorValidacion(f"{campo}: es obligatorio")
        return None
    s = str(valor).strip()
    if not re.fullmatch(r"-?\d+", s):
        raise ErrorValidacion(f"{campo}: '{valor}' debe ser un número entero")
    n = int(s)
    if n < minimo or (maximo is not None and n > maximo):
        raise ErrorValidacion(f"{campo}: debe estar entre {minimo} y {maximo if maximo is not None else '∞'}")
    return n


def validar_datos_base(d):
    """Datos base de una calificación (HU 2): normaliza y valida; devuelve un dict limpio."""
    mercado = str(d.get("mercado", "")).strip().upper()
    if mercado not in MERCADOS:
        raise ErrorValidacion(f"Mercado inválido: use {', '.join(MERCADOS)}")
    tipo = d.get("tipo_sociedad")
    tipo = str(tipo).strip().upper()[:1] if tipo not in (None, "") else None
    if tipo not in (None, "A", "C"):
        raise ErrorValidacion("Tipo de sociedad: use A (abierta) o C (cerrada)")
    desc = (d.get("descripcion") or "").strip()
    if len(desc) > 200:
        raise ErrorValidacion("Descripción: máximo 200 caracteres")
    isfut = d.get("isfut", False)
    isfut = str(isfut).strip().lower() in ("1", "true", "si", "sí", "x", "s") if not isinstance(isfut, bool) else isfut
    vh = d.get("valor_historico")
    fa = d.get("factor_actualizacion")
    fecha = d.get("fecha_pago")
    out = {
        "ejercicio": _entero(d.get("ejercicio"), "Ejercicio", 2000, 2100),
        "mercado": mercado,
        "secuencia": _entero(d.get("secuencia"), "Secuencia", 0, 9999999999),
        "numero_dividendo": _entero(d.get("numero_dividendo"), "Número de dividendo", 0, 9999999999, obligatorio=False),
        "tipo_sociedad": tipo,
        "fecha_pago": parsear_fecha(fecha, "Fecha de pago") if fecha not in (None, "") else None,
        "valor_historico": parsear_numero(vh, "Valor histórico") if vh not in (None, "") else None,
        "descripcion": desc or None,
        "isfut": isfut,
        "factor_actualizacion": parsear_numero(fa, "Factor de actualización") if fa not in (None, "") else None,
    }
    if out["valor_historico"] is not None and out["valor_historico"] < 0:
        raise ErrorValidacion("Valor histórico: no puede ser negativo")
    if out["factor_actualizacion"] is not None and out["factor_actualizacion"] < 0:
        raise ErrorValidacion("Factor de actualización: no puede ser negativo")
    return out
