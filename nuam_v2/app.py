"""API REST del Mantenedor CORE de Calificaciones Tributarias (Nuam Exchange).

Autenticación JWT, control de acceso por rol (RBAC), consultas parametrizadas, log de auditoría,
carga masiva con previsualización, homologación de certificados con IDP/OCR y Object Storage.
"""
import csv
import hashlib
import io
import json
import os
import re
import time
import uuid
import datetime as dt

import jwt
import psycopg2
import psycopg2.errors
import psycopg2.extras
import psycopg2.pool
from flask.json.provider import DefaultJSONProvider
from flask import Flask, g, jsonify, request, Response
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

import core
import homologacion
from core import ErrorValidacion, NROS
from storage import crear_storage

psycopg2.extras.register_uuid()

ENTORNO = os.environ.get("NUAM_ENV", "desarrollo")
SECRET = os.environ.get("JWT_SECRET")
if not SECRET:
    if ENTORNO == "produccion":
        raise RuntimeError("En producción debe definir la variable JWT_SECRET")
    SECRET = "clave-de-desarrollo-cambiar-en-produccion"
DSN = os.environ.get("NUAM_DSN", "host=localhost port=5432 dbname=nuam user=postgres password=postgres")
POOL_MAX = int(os.environ.get("NUAM_POOL_MAX", "60"))
MAX_FILAS_CSV = 50000

pool = psycopg2.pool.ThreadedConnectionPool(1, POOL_MAX, DSN)
storage = crear_storage()
app = Flask(__name__, static_folder="static", static_url_path="/static")


class _Json(DefaultJSONProvider):
    """Fechas en ISO 8601 y decimales como texto exacto (sin perder los 8 decimales)."""
    @staticmethod
    def default(o):
        import datetime, decimal
        if isinstance(o, (datetime.datetime, datetime.date)):
            return o.isoformat()
        if isinstance(o, decimal.Decimal):
            return str(o)
        return DefaultJSONProvider.default(o)


app.json = _Json(app)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.json.sort_keys = False

COLUMNAS_BASE = ["Ejercicio", "Mercado", "Instrumento", "Fecha", "Secuencia", "Numero_dividendo", "Tipo_sociedad", "Valor_historico"]


# ----------------------------------------------------------------- infraestructura
def db():
    if "conn" not in g:
        limite = time.time() + 10          # si el pool está lleno, espera su turno en vez de fallar
        while True:
            try:
                g.conn = pool.getconn()
                break
            except psycopg2.pool.PoolError:
                if time.time() > limite:
                    raise
                time.sleep(0.02)
    return g.conn


@app.teardown_appcontext
def cerrar(_):
    c = g.pop("conn", None)
    if c:
        c.rollback()
        pool.putconn(c)


@app.after_request
def cabeceras_seguridad(r):
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["Referrer-Policy"] = "no-referrer"
    r.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'"
    r.headers["Cache-Control"] = "no-store"
    return r


@app.errorhandler(ErrorValidacion)
def _validacion(e):
    return jsonify(error=str(e)), 422


@app.errorhandler(psycopg2.errors.CheckViolation)
def _check(e):
    return jsonify(error="El dato incumple una regla de negocio de la base de datos"), 422


@app.errorhandler(Exception)
def _generico(e):                          # mensajes genéricos, sin detalles internos
    if isinstance(e, HTTPException):
        return jsonify(error=e.name), e.code
    app.logger.exception(e)
    return jsonify(error="Error interno"), 500


def cur(dict_=True):
    return db().cursor(cursor_factory=psycopg2.extras.RealDictCursor if dict_ else None)


def requiere(*roles):
    def deco(fn):
        def wrapper(*a, **kw):
            tok = request.headers.get("Authorization", "").removeprefix("Bearer ")
            try:
                g.user = jwt.decode(tok, SECRET, algorithms=["HS256"])
            except jwt.PyJWTError:
                return jsonify(error="No autenticado"), 401
            if g.user["rol"] not in roles:
                return jsonify(error="Sin permiso"), 403
            return fn(*a, **kw)
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco


def uid():
    return int(g.user["sub"])


def auditar(accion, entidad, detalle=None):
    with cur(False) as c:
        c.execute("INSERT INTO log_auditoria(id_usuario, accion, entidad, detalle) VALUES (%s,%s,%s,%s)",
                  (uid() if "user" in g else None, accion, entidad, psycopg2.extras.Json(detalle or {}, dumps=lambda o: json.dumps(o, default=str))))


def fmt8(v):
    return None if v is None else f"{v:.8f}"


# ----------------------------------------------------------------- sesión
FALLOS = {}


def bloqueado(email):
    t = [x for x in FALLOS.get(email, []) if time.time() - x < 300]
    FALLOS[email] = t
    return len(t) >= 5


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.get("/")
def inicio():
    return app.send_static_file("index.html")


@app.post("/login")
def login():
    d = request.get_json(force=True, silent=True) or {}
    email = str(d.get("email", ""))
    if bloqueado(email):
        return jsonify(error="Demasiados intentos. Espere 5 minutos."), 429
    with cur() as c:
        c.execute("SELECT u.*, r.nombre_rol FROM usuario u JOIN rol r USING(id_rol) WHERE email=%s", (email,))
        u = c.fetchone()
    if not u or not u["activo"] or not check_password_hash(u["pass_hash"], str(d.get("password", ""))):
        FALLOS.setdefault(email, []).append(time.time())
        return jsonify(error="Credenciales inválidas"), 401
    FALLOS.pop(email, None)
    tok = jwt.encode({"sub": str(u["id_usuario"]), "rol": u["nombre_rol"], "corredor": u["id_corredor"],
                      "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=15)}, SECRET, algorithm="HS256")
    return jsonify(token=tok, rol=u["nombre_rol"], nombre=u["nombre"], id_corredor=u["id_corredor"])


# ----------------------------------------------------------------- catálogos e instrumentos
@app.get("/catalogos")
@requiere("Corredor", "Administrador", "Auditor")
def catalogos():
    with cur() as c:
        c.execute("SELECT codigo, nombre FROM mercado ORDER BY codigo")
        mercados = c.fetchall()
        c.execute("SELECT codigo, fuente FROM origen ORDER BY codigo")
        origenes = c.fetchall()
        c.execute("SELECT nro_factor, nombre FROM factor_catalogo ORDER BY nro_factor")
        factores = c.fetchall()
        corredores = []
        if g.user["rol"] == "Administrador":
            c.execute("SELECT id_corredor, razon_social AS nombre, pais FROM corredor ORDER BY razon_social")
            corredores = c.fetchall()
    return jsonify(mercados=mercados, origenes=origenes, factores=factores, corredores=corredores)


def _instrumentos_visibles():
    """Un corredor ve los instrumentos de la Bolsa y los no inscritos que él mismo creó."""
    if g.user["rol"] == "Corredor":
        return "(i.id_corredor_creador IS NULL OR i.id_corredor_creador = %s)", [g.user["corredor"]]
    return "TRUE", []


@app.get("/instrumentos")
@requiere("Corredor", "Administrador", "Auditor")
def instrumentos():
    cond, params = _instrumentos_visibles()
    mercado = request.args.get("mercado", "")
    if mercado:
        cond += " AND i.mercado = %s"
        params.append(mercado)
    with cur() as c:
        c.execute(f"SELECT i.id_instrumento, i.codigo, i.nombre_emisor, i.pais_emisor, i.mercado, i.inscrito FROM instrumento i "
                  f"WHERE {cond} ORDER BY i.codigo", params)
        return jsonify(c.fetchall())


@app.post("/instrumentos")
@requiere("Corredor")
def crear_instrumento():
    d = request.get_json(force=True, silent=True) or {}
    codigo = str(d.get("codigo", "")).strip()
    if not re.fullmatch(r"[\wÁÉÍÓÚáéíóúñÑ .\-]{2,50}", codigo):
        raise ErrorValidacion("Código de instrumento inválido (2 a 50 caracteres)")
    mercado = str(d.get("mercado", "")).upper()
    if mercado not in core.MERCADOS:
        raise ErrorValidacion("Mercado inválido")
    try:
        with cur() as c:
            c.execute("INSERT INTO instrumento(codigo, nombre_emisor, pais_emisor, mercado, inscrito, id_corredor_creador) "
                      "VALUES (%s,%s,%s,%s,FALSE,%s) RETURNING id_instrumento",
                      (codigo, (d.get("nombre_emisor") or "")[:100] or None, (d.get("pais_emisor") or "")[:30] or None, mercado, g.user["corredor"]))
            nuevo = c.fetchone()["id_instrumento"]
    except psycopg2.errors.UniqueViolation:
        return jsonify(error="Ya existe un instrumento con ese código"), 409
    auditar("Creación instrumento no inscrito", "instrumento", {"id": nuevo, "codigo": codigo})
    db().commit()
    return jsonify(id_instrumento=nuevo), 201


# ----------------------------------------------------------------- calificaciones: consulta
SELECT_CAL = """
SELECT c.id_calificacion, c.id_corredor, co.razon_social AS corredor, c.anio_tributario AS ejercicio, c.mercado,
       i.id_instrumento, i.codigo AS instrumento, i.inscrito, c.fecha_pago, c.secuencia_evento AS secuencia,
       c.numero_dividendo, c.tipo_sociedad, c.valor_historico, c.descripcion, c.isfut, c.factor_actualizacion,
       c.origen, o.fuente, c.id_certificado, c.fecha_modificacion, c.forma_modificacion,
       (SELECT json_object_agg(v.nro_factor, v.factor::text) FROM calificacion_valor v WHERE v.id_calificacion = c.id_calificacion) AS factores,
       (SELECT json_object_agg(v.nro_factor, v.monto::text) FROM calificacion_valor v WHERE v.id_calificacion = c.id_calificacion AND v.monto IS NOT NULL) AS montos
  FROM calificacion_tributaria c
  JOIN instrumento i ON i.id_instrumento = c.id_instrumento
  JOIN origen o ON o.codigo = c.origen
  LEFT JOIN corredor co ON co.id_corredor = c.id_corredor
"""

# Un corredor ve lo suyo y lo de la Bolsa, pero si tiene su propia versión (misma llave) la suya prima.
VISIBILIDAD_CORREDOR = """(c.id_corredor = %s OR (c.id_corredor IS NULL AND NOT EXISTS (
     SELECT 1 FROM calificacion_tributaria x WHERE x.id_corredor = %s AND x.anio_tributario = c.anio_tributario
        AND x.mercado = c.mercado AND x.id_instrumento = c.id_instrumento AND x.secuencia_evento = c.secuencia_evento)))"""


def _visibilidad():
    if g.user["rol"] == "Corredor":
        return VISIBILIDAD_CORREDOR, [g.user["corredor"], g.user["corredor"]]
    return "TRUE", []


@app.get("/calificaciones")
@requiere("Corredor", "Administrador", "Auditor")
def buscar():
    cond, params = _visibilidad()
    a = request.args
    if a.get("mercado"):
        cond += " AND c.mercado = %s"; params.append(a["mercado"])
    if a.get("origen"):
        cond += " AND c.origen = %s"; params.append(a["origen"])
    if a.get("fuente"):
        cond += " AND o.fuente = %s"; params.append(a["fuente"])
    if a.get("anio", "").isdigit():
        cond += " AND c.anio_tributario = %s"; params.append(int(a["anio"]))
    if a.get("instrumento"):
        cond += " AND i.codigo ILIKE %s"; params.append("%" + a["instrumento"] + "%")
    pagina = max(int(a["pagina"]), 1) if a.get("pagina", "").isdigit() else 1
    tam = min(max(int(a["tam"]), 1), 200) if a.get("tam", "").isdigit() else 50
    with cur() as c:
        c.execute(f"SELECT count(*) AS n FROM calificacion_tributaria c JOIN instrumento i ON i.id_instrumento=c.id_instrumento "
                  f"JOIN origen o ON o.codigo=c.origen WHERE {cond}", params)
        total = c.fetchone()["n"]
        c.execute(f"{SELECT_CAL} WHERE {cond} ORDER BY c.anio_tributario DESC, i.codigo, c.secuencia_evento LIMIT %s OFFSET %s",
                  params + [tam, (pagina - 1) * tam])
        filas = c.fetchall()
    return jsonify(total=total, pagina=pagina, tam=tam, filas=filas)


def _obtener(id_cal):
    cond, params = _visibilidad()
    with cur() as c:
        c.execute(f"{SELECT_CAL} WHERE c.id_calificacion = %s AND {cond}", [id_cal] + params)
        return c.fetchone()


@app.get("/calificaciones/<int:id_cal>")
@requiere("Corredor", "Administrador", "Auditor")
def detalle(id_cal):
    r = _obtener(id_cal)
    return (jsonify(r), 200) if r else (jsonify(error="No encontrada"), 404)


# ----------------------------------------------------------------- calificaciones: escritura
def _resolver_valores(d):
    """Aplica el modo de ingreso (por montos o por factores) y devuelve (montos, factores)."""
    modo = d.get("modo", "montos")
    valores = d.get("valores") or {}
    if not isinstance(valores, dict):
        raise ErrorValidacion("Los valores deben enviarse como {numero_de_factor: valor}")
    if modo == "montos":
        return core.calcular_desde_montos(valores)
    if modo == "factores":
        return core.calcular_desde_factores(valores)
    raise ErrorValidacion("Modo de ingreso inválido (use montos o factores)")


def _instrumento_permitido(id_instr):
    try:
        id_instr = int(id_instr)
    except (TypeError, ValueError):
        raise ErrorValidacion("Instrumento inválido")
    cond, params = _instrumentos_visibles()
    with cur() as c:
        c.execute(f"SELECT i.id_instrumento, i.mercado FROM instrumento i WHERE i.id_instrumento = %s AND {cond}", [id_instr] + params)
        r = c.fetchone()
    if not r:
        raise ErrorValidacion("El instrumento no existe o no está disponible para su corredora")
    return r


def _guardar_valores(id_cal, montos, factores):
    with cur(False) as c:
        c.execute("DELETE FROM calificacion_valor WHERE id_calificacion = %s", (id_cal,))
        psycopg2.extras.execute_values(
            c, "INSERT INTO calificacion_valor(id_calificacion, nro_factor, monto, factor) VALUES %s",
            [(id_cal, n, montos.get(n), f) for n, f in sorted(factores.items())])


COLS_CAL = ("anio_tributario", "mercado", "secuencia_evento", "numero_dividendo", "tipo_sociedad", "fecha_pago",
            "valor_historico", "descripcion", "isfut", "factor_actualizacion")


def _vals_base(b):
    return (b["ejercicio"], b["mercado"], b["secuencia"], b["numero_dividendo"], b["tipo_sociedad"], b["fecha_pago"],
            b["valor_historico"], b["descripcion"], b["isfut"], b["factor_actualizacion"])


def _insertar(id_corredor, id_instr, base, montos, factores, origen, forma, id_cert=None):
    with cur() as c:
        c.execute(f"INSERT INTO calificacion_tributaria(id_corredor, id_instrumento, {','.join(COLS_CAL)}, origen, id_certificado, forma_modificacion) "
                  f"VALUES (%s,%s,{','.join(['%s'] * len(COLS_CAL))},%s,%s,%s) RETURNING id_calificacion",
                  (id_corredor, id_instr) + _vals_base(base) + (origen, id_cert, forma))
        nuevo = c.fetchone()["id_calificacion"]
    _guardar_valores(nuevo, montos, factores)
    return nuevo


def _snapshot(r):
    return {"ejercicio": r["ejercicio"], "instrumento": r["instrumento"], "mercado": r["mercado"], "secuencia": r["secuencia"],
            "factores": r["factores"]}


@app.post("/calificaciones/calcular")
@requiere("Corredor")
def calcular():
    """Botón Calcular (HU 3.1): devuelve los factores sin guardar."""
    d = request.get_json(force=True, silent=True) or {}
    montos, factores = _resolver_valores(d)
    suma = sum((f for n, f in factores.items() if n in core.NROS_SUMA), core.Decimal(0))
    return jsonify(factores={str(n): fmt8(f) for n, f in sorted(factores.items())}, suma_8_19=fmt8(suma))


@app.post("/calificaciones")
@requiere("Corredor")
def crear():
    d = request.get_json(force=True, silent=True) or {}
    base = core.validar_datos_base(d)
    instr = _instrumento_permitido(d.get("id_instrumento"))
    montos, factores = _resolver_valores(d)
    id_cert = d.get("id_certificado")
    if id_cert:
        with cur() as c:
            c.execute("SELECT 1 FROM certificado WHERE id_certificado = %s AND id_corredor = %s", (id_cert, g.user["corredor"]))
            if not c.fetchone():
                raise ErrorValidacion("El certificado indicado no existe")
    try:
        nuevo = _insertar(g.user["corredor"], instr["id_instrumento"], base, montos, factores,
                          "Certificado" if id_cert else "Manual",
                          f"Ingreso manual por {d.get('modo', 'montos')}" + (" desde certificado" if id_cert else ""), id_cert)
    except psycopg2.errors.UniqueViolation:
        return jsonify(error="Ya existe una calificación con la misma llave (ejercicio, mercado, instrumento y secuencia). Use Modificar."), 409
    auditar("Creación", "calificacion", {"id": nuevo, "ejercicio": base["ejercicio"], "mercado": base["mercado"], "secuencia": base["secuencia"]})
    db().commit()
    return jsonify(id=nuevo, factores={str(n): fmt8(f) for n, f in sorted(factores.items())}), 201


@app.put("/calificaciones/<int:id_cal>")
@requiere("Corredor")
def editar(id_cal):
    """Modifica una calificación propia. Si es de la Bolsa, crea una versión local del corredor (la de la Bolsa no se altera)."""
    d = request.get_json(force=True, silent=True) or {}
    actual = _obtener(id_cal)
    if not actual:
        return jsonify(error="No encontrada"), 404
    base = core.validar_datos_base(d)
    instr = _instrumento_permitido(d.get("id_instrumento"))
    montos, factores = _resolver_valores(d)
    try:
        if actual["id_corredor"] is None:                       # copia local: no se toca la información de la Bolsa
            nuevo = _insertar(g.user["corredor"], instr["id_instrumento"], base, montos, factores, "Manual",
                              f"Versión local de la calificación de la Bolsa #{id_cal}")
            auditar("Edición (versión local de Bolsa)", "calificacion", {"id": nuevo, "origen_bolsa": id_cal,
                                                                         "antes": _snapshot(actual), "despues": {"factores": {str(n): fmt8(f) for n, f in factores.items()}}})
            db().commit()
            return jsonify(id=nuevo, copia_local=True)
        with cur(False) as c:
            c.execute(f"UPDATE calificacion_tributaria SET id_instrumento=%s, {','.join(k + '=%s' for k in COLS_CAL)}, "
                      f"fecha_modificacion=now(), forma_modificacion=%s WHERE id_calificacion=%s",
                      (instr["id_instrumento"],) + _vals_base(base) + (f"Edición manual por {d.get('modo', 'montos')}", id_cal))
        _guardar_valores(id_cal, montos, factores)
    except psycopg2.errors.UniqueViolation:
        return jsonify(error="Ya existe otra calificación con esa misma llave"), 409
    auditar("Edición", "calificacion", {"id": id_cal, "antes": _snapshot(actual),
                                        "despues": {"factores": {str(n): fmt8(f) for n, f in sorted(factores.items())}}})
    db().commit()
    return jsonify(id=id_cal, copia_local=False)


@app.delete("/calificaciones/<int:id_cal>")
@requiere("Corredor")
def eliminar(id_cal):
    actual = _obtener(id_cal)
    if not actual:
        return jsonify(error="No encontrada"), 404
    if actual["id_corredor"] is None:
        return jsonify(error="Las calificaciones de la Bolsa no se pueden eliminar; puede crear una versión local modificándola"), 403
    with cur(False) as c:
        c.execute("DELETE FROM calificacion_tributaria WHERE id_calificacion = %s", (id_cal,))
    auditar("Eliminación", "calificacion", {"id": id_cal, "antes": _snapshot(actual)})
    db().commit()
    return jsonify(ok=True)


# ----------------------------------------------------------------- carga masiva (CSV) con previsualización
def _nombre_col(h):
    return re.sub(r"[\s_\-]+", "", h.strip().lower().replace("ú", "u").replace("é", "e").replace("í", "i").replace("ó", "o").replace("á", "a"))


def plantilla_csv(tipo):
    pref = "Monto" if tipo == "montos" else "Factor"
    cab = COLUMNAS_BASE + [f"{pref}_{n}" for n in NROS]
    ej = ["2025", "ACN", "Copec", "15-04-2025", "123123", "123456", "A", "1250.50"] + \
         [("100000" if tipo == "montos" else "0.08333333") if n < 20 else ("0" if tipo == "montos" else "0") for n in NROS]
    return ";".join(cab) + "\n" + ";".join(ej) + "\n"


@app.get("/plantilla")
@requiere("Corredor")
def plantilla():
    tipo = request.args.get("tipo", "montos")
    if tipo not in ("montos", "factores"):
        raise ErrorValidacion("Tipo inválido")
    return Response(plantilla_csv(tipo), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=plantilla_{tipo}.csv"})


def _leer_csv(contenido):
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1")
    primera = texto.splitlines()[0] if texto.strip() else ""
    delim = ";" if primera.count(";") >= primera.count(",") else ","
    lector = csv.reader(io.StringIO(texto), delimiter=delim)
    filas = [f for f in lector if any(x.strip() for x in f)]
    if len(filas) < 2:
        raise ErrorValidacion("El archivo no tiene filas de datos")
    if len(filas) - 1 > MAX_FILAS_CSV:
        raise ErrorValidacion(f"El archivo supera el máximo de {MAX_FILAS_CSV} filas")
    return filas[0], filas[1:], delim


def _procesar_csv(contenido, tipo, id_corredor):
    """Valida cada fila y decide si crea o actualiza (por llave). No escribe nada."""
    cab, filas, delim = _leer_csv(contenido)
    idx = {_nombre_col(h): i for i, h in enumerate(cab)}
    base_req = ["ejercicio", "mercado", "instrumento", "fecha", "secuencia"]
    faltan = [c for c in base_req if c not in idx]
    pref = "monto" if tipo == "montos" else "factor"
    cols_val = {n: idx[f"{pref}{n}"] for n in NROS if f"{pref}{n}" in idx}
    if faltan:
        raise ErrorValidacion("Faltan columnas obligatorias: " + ", ".join(faltan))
    if not cols_val:
        raise ErrorValidacion(f"El archivo no tiene columnas {pref.capitalize()}_8 … {pref.capitalize()}_37")
    with cur() as c:
        c.execute("SELECT i.id_instrumento, upper(i.codigo) AS codigo, i.mercado FROM instrumento i WHERE i.id_corredor_creador IS NULL OR i.id_corredor_creador = %s", (id_corredor,))
        instr = {r["codigo"]: r for r in c.fetchall()}
        c.execute("SELECT anio_tributario, mercado, id_instrumento, secuencia_evento FROM calificacion_tributaria WHERE id_corredor = %s", (id_corredor,))
        existentes = {(r["anio_tributario"], r["mercado"], r["id_instrumento"], r["secuencia_evento"]) for r in c.fetchall()}
    vistas, resultado = set(), []

    def val(fila, nombre):
        i = idx.get(nombre)
        return fila[i].strip() if i is not None and i < len(fila) else ""

    for n_fila, fila in enumerate(filas, start=2):
        r = {"linea": n_fila, "estado": "error", "errores": [], "datos": None}
        try:
            d = {"ejercicio": val(fila, "ejercicio"), "mercado": val(fila, "mercado"), "secuencia": val(fila, "secuencia"),
                 "numero_dividendo": val(fila, "numerodividendo"), "tipo_sociedad": val(fila, "tiposociedad"),
                 "fecha_pago": val(fila, "fecha"), "valor_historico": val(fila, "valorhistorico"),
                 "descripcion": val(fila, "descripcion"), "isfut": val(fila, "isfut") or False,
                 "factor_actualizacion": val(fila, "factoractualizacion")}
            base = core.validar_datos_base(d)
            ins = instr.get(val(fila, "instrumento").upper())
            if not ins:
                raise ErrorValidacion(f"Instrumento '{val(fila, 'instrumento')}' no existe (créelo como instrumento no inscrito)")
            if ins["mercado"] != base["mercado"]:
                raise ErrorValidacion(f"El instrumento pertenece al mercado {ins['mercado']}, no a {base['mercado']}")
            valores = {n: fila[i] for n, i in cols_val.items() if i < len(fila) and fila[i].strip() != ""}
            montos, factores = core.calcular_desde_montos(valores) if tipo == "montos" else core.calcular_desde_factores(valores)
            llave = (base["ejercicio"], base["mercado"], ins["id_instrumento"], base["secuencia"])
            if llave in vistas:
                raise ErrorValidacion("La llave (ejercicio, mercado, instrumento, secuencia) está repetida en el archivo")
            vistas.add(llave)
            r.update(estado="actualiza" if llave in existentes else "nueva",
                     datos={"base": base, "id_instrumento": ins["id_instrumento"], "instrumento": val(fila, "instrumento"), "montos": montos, "factores": factores})
        except ErrorValidacion as e:
            r["errores"].append(str(e))
        resultado.append(r)
    return resultado


def _resumen_fila(r):
    d = r["datos"]
    out = {"linea": r["linea"], "estado": r["estado"], "errores": r["errores"]}
    if d:
        out.update(ejercicio=d["base"]["ejercicio"], mercado=d["base"]["mercado"], instrumento=d["instrumento"], secuencia=d["base"]["secuencia"],
                   factores={str(n): fmt8(f) for n, f in sorted(d["factores"].items())})
    return out


@app.post("/calificaciones/csv")
@requiere("Corredor")
def carga_csv():
    """modo=previsualizar muestra el resultado sin guardar; modo=confirmar guarda todo o nada (crea o actualiza por llave)."""
    f = request.files.get("archivo")
    tipo = request.args.get("tipo", "montos")
    modo = request.args.get("modo", "previsualizar")
    if tipo not in ("montos", "factores") or modo not in ("previsualizar", "confirmar"):
        raise ErrorValidacion("Parámetros inválidos")
    if not f or not f.filename.lower().endswith(".csv"):
        raise ErrorValidacion("Solo se aceptan archivos CSV")
    contenido = f.read()
    res = _procesar_csv(contenido, tipo, g.user["corredor"])
    errores = [r for r in res if r["estado"] == "error"]
    resumen = {"total": len(res), "nuevas": sum(r["estado"] == "nueva" for r in res),
               "actualizan": sum(r["estado"] == "actualiza" for r in res), "con_errores": len(errores)}
    if modo == "previsualizar":
        mostrar = errores[:200] + [r for r in res if r["estado"] != "error"][:100]
        return jsonify(resumen=resumen, filas=[_resumen_fila(r) for r in sorted(mostrar, key=lambda x: x["linea"])])
    if errores:
        return jsonify(error=f"El archivo tiene {len(errores)} fila(s) con errores; no se guardó nada", resumen=resumen,
                       filas=[_resumen_fila(r) for r in errores[:200]]), 422
    lote = uuid.uuid4().hex[:12]
    storage.put(f"lote_{lote}.csv", contenido, "text/csv")          # el archivo original queda como respaldo
    origen = "Carga masiva montos" if tipo == "montos" else "Carga masiva factores"
    forma = f"Carga masiva CSV ({tipo}) lote {lote}"
    for r in res:
        d = r["datos"]
        if r["estado"] == "nueva":
            _insertar(g.user["corredor"], d["id_instrumento"], d["base"], d["montos"], d["factores"], origen, forma)
        else:
            with cur() as c:
                c.execute(f"UPDATE calificacion_tributaria SET {','.join(k + '=%s' for k in COLS_CAL)}, origen=%s, fecha_modificacion=now(), forma_modificacion=%s "
                          "WHERE id_corredor=%s AND anio_tributario=%s AND mercado=%s AND id_instrumento=%s AND secuencia_evento=%s RETURNING id_calificacion",
                          _vals_base(d["base"]) + (origen, forma, g.user["corredor"], d["base"]["ejercicio"], d["base"]["mercado"], d["id_instrumento"], d["base"]["secuencia"]))
                _guardar_valores(c.fetchone()["id_calificacion"], d["montos"], d["factores"])
    auditar("Carga masiva", "lote", {"lote": lote, "tipo": tipo, "archivo": f.filename, **resumen})
    db().commit()
    return jsonify(resumen=resumen, lote=lote), 201


# ----------------------------------------------------------------- certificados (IDP/OCR + homologación)
@app.post("/certificados")
@requiere("Corredor")
def subir_certificado():
    """Guarda el PDF, lo lee (con OCR si es una imagen), homologa sus columnas y devuelve los datos para revisar y grabar."""
    f = request.files.get("archivo")
    if not f or not f.filename.lower().endswith(".pdf"):
        raise ErrorValidacion("Solo se aceptan archivos PDF")
    raw = f.read()
    if not raw.startswith(b"%PDF"):
        raise ErrorValidacion("El archivo no es un PDF válido")
    texto, ocr = homologacion.extraer_texto(raw)
    datos = homologacion.parsear_certificado(texto)
    with cur() as c:
        c.execute("SELECT columna_origen, nro_factor FROM homologacion_columna WHERE tipo_certificado = %s", (datos["tipo"],))
        mapa = {r["columna_origen"]: r["nro_factor"] for r in c.fetchall()}
    montos, sin_mapeo = homologacion.homologar(datos["columnas"], mapa)
    idc = uuid.uuid4()
    extraccion = {"tipo": datos["tipo"], "ocr_usado": ocr, "datos_base": {k: v for k, v in datos.items() if k not in ("columnas", "tipo")},
                  "columnas_origen": datos["columnas"], "montos_homologados": {str(n): str(m) for n, m in montos.items()}}
    storage.put(f"cert_{idc}.pdf", raw, "application/pdf")
    storage.put(f"idp_{idc}.json", json.dumps(extraccion, ensure_ascii=False).encode(), "application/json")
    with cur(False) as c:
        c.execute("INSERT INTO certificado(id_certificado, id_corredor, tipo, archivo, archivo_json, sha256, ocr_usado, extraccion) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                  (idc, g.user["corredor"], datos["tipo"], f"cert_{idc}.pdf", f"idp_{idc}.json", hashlib.sha256(raw).hexdigest(), ocr, psycopg2.extras.Json(extraccion)))
    auditar("Homologación certificado", "certificado", {"id_certificado": str(idc), "tipo": datos["tipo"], "ocr": ocr})
    db().commit()
    base = extraccion["datos_base"]
    instrumento = None
    if base.get("instrumento"):
        cond, params = _instrumentos_visibles()
        with cur() as c:
            c.execute(f"SELECT i.id_instrumento, i.codigo, i.mercado FROM instrumento i WHERE upper(i.codigo) = upper(%s) AND {cond}", [base["instrumento"]] + params)
            instrumento = c.fetchone()
    return jsonify(id_certificado=str(idc), tipo=datos["tipo"], ocr_usado=ocr, datos_base=base, instrumento=instrumento,
                   montos={str(n): str(m) for n, m in sorted(montos.items())}, columnas_sin_mapeo=sin_mapeo), 201


@app.get("/certificados/<uuid:idc>/archivo")
@requiere("Corredor", "Administrador", "Auditor")
def descargar_certificado(idc):
    """Re-extracción ante reclamos: devuelve el PDF original del certificado."""
    with cur() as c:
        c.execute("SELECT id_corredor, archivo FROM certificado WHERE id_certificado = %s", (idc,))
        r = c.fetchone()
    if not r or (g.user["rol"] == "Corredor" and r["id_corredor"] != g.user["corredor"]):
        return jsonify(error="No encontrado"), 404
    auditar("Descarga certificado", "certificado", {"id_certificado": str(idc)})
    db().commit()
    return Response(storage.get(r["archivo"]), mimetype="application/pdf")


# ----------------------------------------------------------------- administración y auditoría
@app.get("/usuarios")
@requiere("Administrador")
def listar_usuarios():
    with cur() as c:
        c.execute("SELECT u.id_usuario, u.nombre, u.email, r.nombre_rol AS rol, u.pais, u.activo, u.id_corredor FROM usuario u JOIN rol r USING(id_rol) ORDER BY u.id_usuario")
        return jsonify(c.fetchall())


@app.post("/usuarios")
@requiere("Administrador")
def crear_usuario():
    d = request.get_json(force=True, silent=True) or {}
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(d.get("email", ""))):
        raise ErrorValidacion("Email inválido")
    if len(str(d.get("password", ""))) < 8:
        raise ErrorValidacion("La contraseña debe tener al menos 8 caracteres")
    if not str(d.get("nombre", "")).strip():
        raise ErrorValidacion("El nombre es obligatorio")
    with cur() as c:
        c.execute("SELECT id_rol FROM rol WHERE nombre_rol = %s", (d.get("rol"),))
        r = c.fetchone()
        if not r:
            raise ErrorValidacion("Rol inválido")
        if r["id_rol"] == 1 and not d.get("id_corredor"):
            raise ErrorValidacion("Un usuario Corredor debe pertenecer a una corredora")
        try:
            c.execute("INSERT INTO usuario(nombre,email,pass_hash,id_rol,id_corredor,pais) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id_usuario",
                      (d["nombre"].strip(), d["email"], generate_password_hash(d["password"]), r["id_rol"], d.get("id_corredor"), d.get("pais")))
        except psycopg2.errors.UniqueViolation:
            return jsonify(error="Ya existe un usuario con ese correo"), 409
        except psycopg2.errors.ForeignKeyViolation:
            return jsonify(error="La corredora indicada no existe"), 422
        nuevo = c.fetchone()["id_usuario"]
    auditar("Creación usuario", "usuario", {"id": nuevo, "rol": d["rol"]})
    db().commit()
    return jsonify(id=nuevo), 201


@app.put("/usuarios/<int:id_u>")
@requiere("Administrador")
def modificar_usuario(id_u):
    d = request.get_json(force=True, silent=True) or {}
    with cur() as c:
        if "rol" in d:
            c.execute("SELECT id_rol FROM rol WHERE nombre_rol = %s", (d["rol"],))
            r = c.fetchone()
            if not r:
                raise ErrorValidacion("Rol inválido")
            try:
                c.execute("UPDATE usuario SET id_rol = %s WHERE id_usuario = %s", (r["id_rol"], id_u))
            except psycopg2.errors.CheckViolation:
                raise ErrorValidacion("Un usuario Corredor debe pertenecer a una corredora")
        if "activo" in d:
            c.execute("UPDATE usuario SET activo = %s WHERE id_usuario = %s", (bool(d["activo"]), id_u))
    auditar("Modificación usuario", "usuario", {"id": id_u, "cambios": {k: d[k] for k in ("rol", "activo") if k in d}})
    db().commit()
    return jsonify(ok=True)


@app.get("/log")
@requiere("Auditor", "Administrador")
def ver_log():
    accion = request.args.get("accion", "")
    with cur() as c:
        c.execute("SELECT l.id_log, l.id_usuario, u.nombre AS usuario, l.accion, l.entidad, l.detalle, l.ts FROM log_auditoria l "
                  "LEFT JOIN usuario u ON u.id_usuario = l.id_usuario WHERE (%s = '' OR l.accion ILIKE %s) ORDER BY l.id_log DESC LIMIT 200",
                  (accion, "%" + accion + "%"))
        return jsonify([{**r, "ts": r["ts"].isoformat()} for r in c.fetchall()])


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", "5055")), threaded=True)
