"""Pruebas de la API trazadas a los requisitos funcionales RF1 a RF13 y a las reglas de negocio."""
import io
import json

import psycopg2

from conftest import (DSN, crear, cuerpo, ids_instrumentos, listar, pdf_escaneado, pdf_texto, subir_csv, subir_pdf, csv_montos)

BOLSA = "Sistema/Bolsa"


# ---------------------------------------------------------------- RF1 / RF2: mantenedor y búsqueda
def test_RF1_filtros_mercado_origen_periodo(cliente, ha):
    crear(cliente, ha, secuencia=1)
    crear(cliente, ha, secuencia=2, ejercicio=2024)
    crear(cliente, ha, secuencia=3, mercado="CFI", id_instrumento=ids_instrumentos(cliente, ha)["CFI-RENTA"])
    assert listar(cliente, ha, mercado="CFI")["total"] == 1 + 1          # la propia + la de la Bolsa (CFI)
    assert {f["ejercicio"] for f in listar(cliente, ha, anio=2024)["filas"]} == {2024}
    assert all(f["origen"] == "Manual" for f in listar(cliente, ha, origen="Manual")["filas"])
    fuentes = {f["fuente"] for f in listar(cliente, ha)["filas"]}
    assert fuentes == {"Corredor", "Entidad prestadora"}
    assert all(f["fuente"] == "Entidad prestadora" for f in listar(cliente, ha, fuente="Entidad prestadora")["filas"])
    assert listar(cliente, ha, instrumento="cop")["total"] >= 2


def test_RF2_busqueda_paginada(cliente, ha):
    for s in range(1, 13):
        crear(cliente, ha, secuencia=s)
    r = listar(cliente, ha, tam=5, pagina=2)
    assert r["total"] >= 12 and len(r["filas"]) == 5 and r["pagina"] == 2
    assert listar(cliente, ha, tam=1000)["tam"] == 200           # tope de página


# ---------------------------------------------------------------- RF3 / RF4 / RF5 / RF6: CRUD, datos base y cálculo
def test_RF4_ingreso_con_todos_los_datos_base(cliente, ha):
    idc = crear(cliente, ha)
    r = cliente.get(f"/calificaciones/{idc}", headers=ha).get_json()
    assert (r["ejercicio"], r["mercado"], r["secuencia"], r["numero_dividendo"], r["tipo_sociedad"]) == (2025, "ACN", 100, 1, "A")
    assert r["fecha_pago"] == "2025-04-15" and r["valor_historico"] == "1250.50" and r["descripcion"] == "Dividendo de prueba"
    assert r["isfut"] is False and r["factor_actualizacion"] == "1.02000000" and r["origen"] == "Manual"


def test_RF5_RF6_calcular_y_grabar_por_montos(cliente, ha):
    r = cliente.post("/calificaciones/calcular", headers=ha, json={"modo": "montos", "valores": {"8": 400000, "9": 350000, "10": 250000, "20": 100000}})
    d = r.get_json()
    assert r.status_code == 200 and d["factores"]["8"] == "0.40000000" and d["factores"]["20"] == "0.10000000" and d["suma_8_19"] == "1.00000000"
    idc = crear(cliente, ha)
    det = cliente.get(f"/calificaciones/{idc}", headers=ha).get_json()
    assert det["factores"]["9"] == "0.35000000" and det["montos"]["9"] == "350000.00"


def test_RF6_30_factores_del_8_al_37(cliente, ha):
    valores = {str(n): (1000 if n < 20 else 10) for n in range(8, 38)}
    idc = crear(cliente, ha, valores=valores)
    det = cliente.get(f"/calificaciones/{idc}", headers=ha).get_json()
    assert sorted(int(k) for k in det["factores"]) == list(range(8, 38))


def test_RF6_suma_mayor_a_1_se_bloquea(cliente, ha):
    r = cliente.post("/calificaciones", headers=ha, json=cuerpo(cliente, ha, modo="factores", valores={"8": "0.5", "9": "0.55"}))
    assert r.status_code == 422 and "supera 1" in r.get_json()["error"]
    assert listar(cliente, ha, origen="Manual")["total"] == 0


def test_RF7_ingreso_directo_por_factores(cliente, ha):
    idc = crear(cliente, ha, modo="factores", valores={"8": "0.92345300", "9": "0.07654700", "20": "0.5"})
    det = cliente.get(f"/calificaciones/{idc}", headers=ha).get_json()
    assert det["factores"]["8"] == "0.92345300" and det["montos"] is None


def test_RF3_modificar_y_eliminar_con_log_antes_despues(cliente, ha, hb, bd):
    idc = crear(cliente, ha)
    r = cliente.put(f"/calificaciones/{idc}", headers=ha, json=cuerpo(cliente, ha, descripcion="Corregida", valores={"8": 250, "9": 750}))
    assert r.status_code == 200 and r.get_json()["copia_local"] is False
    det = cliente.get(f"/calificaciones/{idc}", headers=ha).get_json()
    assert det["factores"]["8"] == "0.25000000" and det["descripcion"] == "Corregida" and "Edición manual" in det["forma_modificacion"]
    assert "20" not in det["factores"]                                              # los valores se reemplazan completos
    assert cliente.put(f"/calificaciones/{idc}", headers=hb, json=cuerpo(cliente, hb)).status_code == 404
    assert cliente.delete(f"/calificaciones/{idc}", headers=hb).status_code == 404
    assert cliente.delete(f"/calificaciones/{idc}", headers=ha).status_code == 200
    assert cliente.get(f"/calificaciones/{idc}", headers=ha).status_code == 404
    cur = bd.cursor()
    cur.execute("SELECT detalle FROM log_auditoria WHERE accion = 'Edición'")
    det = cur.fetchone()[0]
    assert det["antes"]["factores"]["8"] == "0.40000000" and det["despues"]["factores"]["8"] == "0.25000000"
    cur.execute("SELECT count(*) FROM log_auditoria WHERE accion = 'Eliminación'")
    assert cur.fetchone()[0] == 1


def test_RF3_llave_duplicada_devuelve_409(cliente, ha):
    crear(cliente, ha)
    r = cliente.post("/calificaciones", headers=ha, json=cuerpo(cliente, ha))
    assert r.status_code == 409 and "Modificar" in r.get_json()["error"]


# ---------------------------------------------------------------- RF8: instrumentos no inscritos
def test_RF8_instrumento_no_inscrito_es_local_del_corredor(cliente, ha, hb):
    r = cliente.post("/instrumentos", headers=ha, json={"codigo": "EMPRESA-X", "nombre_emisor": "Empresa X SpA", "mercado": "ACN"})
    assert r.status_code == 201
    id_x = r.get_json()["id_instrumento"]
    assert "EMPRESA-X" in ids_instrumentos(cliente, ha) and "EMPRESA-X" not in ids_instrumentos(cliente, hb)
    assert next(i for i in cliente.get("/instrumentos", headers=ha).get_json() if i["codigo"] == "EMPRESA-X")["inscrito"] is False
    crear(cliente, ha, id_instrumento=id_x)
    assert cliente.post("/instrumentos", headers=ha, json={"codigo": "empresa-x", "mercado": "ACN"}).status_code == 409
    r = cliente.post("/calificaciones", headers=hb, json=cuerpo(cliente, hb, id_instrumento=id_x))
    assert r.status_code == 422                                                       # B no puede usar el de A
    assert cliente.post("/instrumentos", headers=ha, json={"codigo": "x", "mercado": "ACN"}).status_code == 422


# ---------------------------------------------------------------- RF9 / RF10: carga masiva
def fila(seq, monto=100000, instr="Copec", ej=2025, mer="ACN"):
    return [ej, mer, instr, "15-04-2025", seq, 1, "A", "1250.50", monto, 100000, 100000, 0]


def test_RF9_previsualizar_no_guarda_nada(cliente, ha):
    r = subir_csv(cliente, ha, csv_montos([fila(1), fila(2)]))
    d = r.get_json()
    assert r.status_code == 200 and d["resumen"] == {"total": 2, "nuevas": 2, "actualizan": 0, "con_errores": 0}
    assert d["filas"][0]["factores"]["8"] == "0.33333333"                              # muestra los factores calculados
    assert listar(cliente, ha, origen="Carga masiva montos")["total"] == 0


def test_RF9_validacion_de_formato_por_fila(cliente, ha):
    malo = csv_montos([fila(1), fila(2, instr="NoExiste"), [2025, "XXX", "Copec", "15-04-2025", 3, 1, "A", 1, 1, 1, 1, 0],
                       [2025, "ACN", "Copec", "31-02-2025", 4, 1, "A", 1, 1, 1, 1, 0], fila(1)])
    d = subir_csv(cliente, ha, malo).get_json()
    assert d["resumen"]["con_errores"] == 4 and d["resumen"]["nuevas"] == 1
    errs = {f["linea"]: f["errores"][0] for f in d["filas"] if f["estado"] == "error"}
    assert "no existe" in errs[3] and "Mercado" in errs[4] and "fecha" in errs[5].lower() and "repetida" in errs[6]
    r = subir_csv(cliente, ha, malo, modo="confirmar")
    assert r.status_code == 422 and listar(cliente, ha, origen="Carga masiva montos")["total"] == 0     # todo o nada


def test_RF9_carga_por_montos_y_por_factores(cliente, ha):
    assert subir_csv(cliente, ha, csv_montos([fila(1), fila(2)]), modo="confirmar").status_code == 201
    cab = "Ejercicio;Mercado;Instrumento;Fecha;Secuencia;Factor_8;Factor_9\n"
    r = subir_csv(cliente, ha, cab + "2025;ACN;BCO-SAN;01-06-2025;77;0,923453;0,076547\n", tipo="factores", modo="confirmar")
    assert r.status_code == 201
    filas = {f["secuencia"]: f for f in listar(cliente, ha, tam=200)["filas"] if f["origen"].startswith("Carga")}
    assert filas[1]["origen"] == "Carga masiva montos" and filas[77]["origen"] == "Carga masiva factores"
    assert filas[77]["factores"]["8"] == "0.92345300"


def test_RF9_formatos_coma_y_punto_y_coma_y_plantilla(cliente, ha):
    r = subir_csv(cliente, ha, csv_montos([fila(1)], delim=","))
    assert r.get_json()["resumen"]["nuevas"] == 1
    for tipo in ("montos", "factores"):
        pl = cliente.get(f"/plantilla?tipo={tipo}", headers=ha).data.decode()
        d = subir_csv(cliente, ha, pl, tipo=tipo).get_json()
        assert d["resumen"]["con_errores"] == 0, d                                     # la plantilla descargable es válida


def test_RF9_archivos_invalidos(cliente, ha):
    assert subir_csv(cliente, ha, "solo-encabezado\n").status_code == 422
    assert subir_csv(cliente, ha, "A;B\n1;2\n").status_code == 422                     # faltan columnas obligatorias
    assert subir_csv(cliente, ha, csv_montos([fila(1)]), nombre="x.exe").status_code == 422
    assert subir_csv(cliente, ha, csv_montos([fila(1)]), tipo="otro").status_code == 422


def test_RF10_crear_si_no_existe_actualizar_si_existe(cliente, ha, bd):
    subir_csv(cliente, ha, csv_montos([fila(1), fila(2)]), modo="confirmar")
    antes = {f["secuencia"]: f for f in listar(cliente, ha, origen="Carga masiva montos")["filas"]}
    r = subir_csv(cliente, ha, csv_montos([fila(1, monto=300000), fila(3)]))
    assert r.get_json()["resumen"] == {"total": 2, "nuevas": 1, "actualizan": 1, "con_errores": 0}
    assert subir_csv(cliente, ha, csv_montos([fila(1, monto=300000), fila(3)]), modo="confirmar").status_code == 201
    desp = {f["secuencia"]: f for f in listar(cliente, ha, origen="Carga masiva montos")["filas"]}
    assert sorted(desp) == [1, 2, 3] and desp[1]["id_calificacion"] == antes[1]["id_calificacion"]      # se actualizó, no se duplicó
    assert desp[1]["factores"]["8"] == "0.60000000" and desp[2]["factores"]["8"] == antes[2]["factores"]["8"]
    assert "Carga masiva CSV (montos) lote" in desp[1]["forma_modificacion"] and desp[1]["fecha_modificacion"] > antes[1]["fecha_modificacion"]
    cur = bd.cursor()
    cur.execute("SELECT detalle FROM log_auditoria WHERE accion = 'Carga masiva' ORDER BY id_log DESC LIMIT 1")
    d = cur.fetchone()[0]
    assert d["nuevas"] == 1 and d["actualizan"] == 1 and d["archivo"] == "lote.csv"


# ---------------------------------------------------------------- RF11 / RF12: origen y log
def test_RF11_columna_origen_en_todas_las_vias(cliente, ha):
    crear(cliente, ha, secuencia=1)
    subir_csv(cliente, ha, csv_montos([fila(2)]), modo="confirmar")
    up = subir_pdf(cliente, ha, pdf_texto()).get_json()
    b = up["datos_base"]
    cliente.post("/calificaciones", headers=ha, json=cuerpo(cliente, ha, secuencia=int(b["secuencia"]), id_certificado=up["id_certificado"], valores=up["montos"]))
    origenes = {f["origen"] for f in listar(cliente, ha, tam=200)["filas"]}
    assert origenes == {"Manual", "Carga masiva montos", "Certificado", BOLSA}


def test_RF12_log_de_ingreso_modificacion_eliminacion(cliente, ha, haud):
    idc = crear(cliente, ha)
    cliente.put(f"/calificaciones/{idc}", headers=ha, json=cuerpo(cliente, ha, valores={"8": 1, "9": 1}))
    cliente.delete(f"/calificaciones/{idc}", headers=ha)
    acciones = [x["accion"] for x in cliente.get("/log", headers=haud).get_json()]
    assert acciones.count("Creación") == 1 and acciones.count("Edición") == 1 and acciones.count("Eliminación") == 1
    assert cliente.get("/log?accion=Elimin", headers=haud).get_json()[0]["usuario"] == "Corredor A"


# ---------------------------------------------------------------- RF13: IDP/OCR y homologación
def test_RF13_certificado_70_con_texto(cliente, ha, bd):
    r = subir_pdf(cliente, ha, pdf_texto("70"))
    d = r.get_json()
    assert r.status_code == 201 and d["tipo"] == "70" and d["ocr_usado"] is False
    assert d["datos_base"]["ejercicio"] == "2025" and d["datos_base"]["secuencia"] == "500" and d["instrumento"]["codigo"] == "COPEC"
    assert d["montos"] == {"8": "400000", "9": "350000", "10": "250000", "20": "100000"}
    cur = bd.cursor()
    cur.execute("SELECT tipo, archivo, archivo_json, extraccion->>'tipo' FROM certificado")
    tipo, arch, js, t = cur.fetchone()
    assert tipo == "70" and t == "70"
    assert appmod_storage().existe(arch) and appmod_storage().existe(js)           # PDF y JSON en el Object Storage


def appmod_storage():
    import app
    return app.storage


def test_RF13_certificado_44_y_dj(cliente, ha):
    assert subir_pdf(cliente, ha, pdf_texto("44")).get_json()["tipo"] == "44"
    dj = pdf_texto("70").replace(b"Certificado 70", b"DJ 1922")
    # DJ 1948 -> Certificado 70 ; DJ 1922 -> Certificado 44 (se prueba con un PDF generado con ese encabezado)
    from reportlab.pdfgen import canvas
    for dj_n, esperado in (("1948", "70"), ("1922", "44")):
        buf = io.BytesIO()
        p = canvas.Canvas(buf)
        for i, l in enumerate([f"Declaracion Jurada DJ {dj_n}", "Ejercicio: 2025", "Columna 8: 1000", "Columna 9: 500"]):
            p.drawString(72, 790 - 18 * i, l)
        p.save()
        assert subir_pdf(cliente, ha, buf.getvalue()).get_json()["tipo"] == esperado


def test_RF13_homologacion_de_columnas_configurable(cliente, ha, bd):
    """Si el formato Certificado 44 usa la columna 12 para lo que internamente es el factor 8, se homologa."""
    cur = bd.cursor()
    cur.execute("UPDATE homologacion_columna SET nro_factor = 8 WHERE tipo_certificado = '44' AND columna_origen = 12")
    cur.execute("UPDATE homologacion_columna SET nro_factor = 12 WHERE tipo_certificado = '44' AND columna_origen = 8")
    bd.commit()
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    p = canvas.Canvas(buf)
    for i, l in enumerate(["Certificado 44", "Ejercicio: 2025", "Columna 8: 111", "Columna 12: 999"]):
        p.drawString(72, 790 - 18 * i, l)
    p.save()
    d = subir_pdf(cliente, ha, buf.getvalue()).get_json()
    assert d["montos"] == {"8": "999", "12": "111"}


def test_RF13_certificado_escaneado_usa_ocr(cliente, ha):
    r = subir_pdf(cliente, ha, pdf_escaneado())
    d = r.get_json()
    assert r.status_code == 201, d
    assert d["ocr_usado"] is True and d["tipo"] == "70"
    assert d["montos"].get("8") == "400000" and d["montos"].get("9") == "350000" and d["montos"].get("10") == "250000"
    assert d["datos_base"]["mercado"] == "ACN"


def test_RF13_certificado_invalido(cliente, ha):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    p = canvas.Canvas(buf)
    p.drawString(72, 780, "Factura de servicios de internet numero 99, total a pagar 15000")
    p.save()
    assert subir_pdf(cliente, ha, buf.getvalue()).status_code == 422                   # no es certificado
    assert subir_pdf(cliente, ha, b"no soy pdf", "x.pdf").status_code == 422
    assert subir_pdf(cliente, ha, b"MZ.....", "x.exe").status_code == 422


def test_RF13_certificado_original_se_puede_volver_a_descargar(cliente, ha, hb, haud):
    pdf = pdf_texto("70")
    idc = subir_pdf(cliente, ha, pdf).get_json()["id_certificado"]
    assert cliente.get(f"/certificados/{idc}/archivo", headers=ha).data == pdf          # re-extracción ante reclamos
    assert cliente.get(f"/certificados/{idc}/archivo", headers=haud).status_code == 200
    assert cliente.get(f"/certificados/{idc}/archivo", headers=hb).status_code == 404


# ---------------------------------------------------------------- Reglas de negocio: Bolsa vs corredor
def bolsa_de(cliente, h, seq=9001):
    return next(f for f in listar(cliente, h, tam=200)["filas"] if f["secuencia"] == seq and f["origen"] == BOLSA)


def test_REGLA_el_corredor_ve_la_info_de_la_bolsa(cliente, ha, hb):
    assert bolsa_de(cliente, ha)["fuente"] == "Entidad prestadora" and bolsa_de(cliente, hb)["id_corredor"] is None


def test_REGLA_editar_calificacion_de_bolsa_crea_version_local_y_prima(cliente, ha, hb, bd):
    bol = bolsa_de(cliente, ha)
    cur = bd.cursor()
    cur.execute("SELECT count(*), max(fecha_modificacion) FROM calificacion_tributaria WHERE origen = 'Sistema/Bolsa'")
    n_bolsa, fecha_bolsa = cur.fetchone()
    cur.execute("SELECT string_agg(nro_factor || '=' || factor, ',' ORDER BY nro_factor) FROM calificacion_valor WHERE id_calificacion = %s", (bol["id_calificacion"],))
    factores_bolsa = cur.fetchone()[0]
    r = cliente.put(f"/calificaciones/{bol['id_calificacion']}", headers=ha,
                    json=cuerpo(cliente, ha, ejercicio=2025, secuencia=9001, id_instrumento=bol["id_instrumento"], descripcion="Ajuste del corredor A",
                                modo="factores", valores={"8": "0.5", "9": "0.5"}))
    assert r.status_code == 200 and r.get_json()["copia_local"] is True
    # A ve SU versión (prima) y no la de la Bolsa; B sigue viendo la de la Bolsa
    mias = [f for f in listar(cliente, ha, tam=200)["filas"] if f["secuencia"] == 9001]
    assert len(mias) == 1 and mias[0]["origen"] == "Manual" and mias[0]["descripcion"] == "Ajuste del corredor A" and mias[0]["factores"]["8"] == "0.50000000"
    assert [f["origen"] for f in listar(cliente, hb, tam=200)["filas"] if f["secuencia"] == 9001] == [BOLSA]
    # La información de la Bolsa quedó intacta
    cur.execute("SELECT count(*), max(fecha_modificacion) FROM calificacion_tributaria WHERE origen = 'Sistema/Bolsa'")
    assert cur.fetchone() == (n_bolsa, fecha_bolsa)
    cur.execute("SELECT string_agg(nro_factor || '=' || factor, ',' ORDER BY nro_factor) FROM calificacion_valor WHERE id_calificacion = %s", (bol["id_calificacion"],))
    assert cur.fetchone()[0] == factores_bolsa
    # Al eliminar su versión local reaparece la de la Bolsa
    assert cliente.delete(f"/calificaciones/{mias[0]['id_calificacion']}", headers=ha).status_code == 200
    assert [f["origen"] for f in listar(cliente, ha, tam=200)["filas"] if f["secuencia"] == 9001] == [BOLSA]


def test_REGLA_la_bolsa_no_se_puede_eliminar(cliente, ha):
    r = cliente.delete(f"/calificaciones/{bolsa_de(cliente, ha)['id_calificacion']}", headers=ha)
    assert r.status_code == 403 and "Bolsa" in r.get_json()["error"]


def test_REGLA_lo_ingresado_es_local_para_cada_corredor(cliente, ha, hb):
    crear(cliente, ha, secuencia=555)
    assert [f for f in listar(cliente, hb, tam=200)["filas"] if f["secuencia"] == 555] == []
    assert any(f["secuencia"] == 555 for f in listar(cliente, ha, tam=200)["filas"])


def test_REGLA_ningun_ingreso_masivo_altera_la_bolsa(cliente, ha, bd):
    """Una carga con la misma llave que una calificación de la Bolsa crea una versión local; la de la Bolsa no cambia."""
    cur = bd.cursor()
    cur.execute("SELECT id_calificacion, descripcion FROM calificacion_tributaria WHERE origen = 'Sistema/Bolsa' AND secuencia_evento = 9001")
    id_b, desc_b = cur.fetchone()
    r = subir_csv(cliente, ha, csv_montos([[2025, "ACN", "Copec", "15-04-2025", 9001, 1, "A", 1, 7, 3, 0, 0]]), modo="confirmar")
    assert r.status_code == 201
    cur.execute("SELECT descripcion, origen FROM calificacion_tributaria WHERE id_calificacion = %s", (id_b,))
    assert cur.fetchone() == (desc_b, BOLSA)
    cur.execute("SELECT factor FROM calificacion_valor WHERE id_calificacion = %s AND nro_factor = 8", (id_b,))
    assert str(cur.fetchone()[0]) == "0.40000000"


def test_REGLA_auditor_y_administrador_ven_todo_en_solo_lectura(cliente, ha, hb, haud, hadm):
    crear(cliente, ha, secuencia=1)
    crear(cliente, hb, secuencia=2)
    for h in (haud, hadm):
        seqs = {f["secuencia"] for f in listar(cliente, h, tam=200)["filas"]}
        assert {1, 2} <= seqs
    assert cliente.post("/calificaciones", headers=haud, json=cuerpo(cliente, ha)).status_code == 403
    assert cliente.post("/calificaciones", headers=hadm, json=cuerpo(cliente, ha)).status_code == 403


# ---------------------------------------------------------------- Catálogos y administración
def test_catalogos(cliente, ha):
    d = cliente.get("/catalogos", headers=ha).get_json()
    assert [m["codigo"] for m in d["mercados"]] == ["ACN", "CFI", "FMU"] and len(d["factores"]) == 30
    assert {o["codigo"] for o in d["origenes"]} >= {"Manual", "Certificado", BOLSA}


def test_administracion_de_usuarios(cliente, ha, hadm):
    assert cliente.get("/usuarios", headers=ha).status_code == 403
    base = {"nombre": "Prueba", "email": "prueba1@nuam.com", "password": "clave-larga-1", "rol": "Auditor"}
    assert cliente.post("/usuarios", headers=hadm, json={**base, "password": "corta"}).status_code == 422
    assert cliente.post("/usuarios", headers=hadm, json={**base, "email": "malo"}).status_code == 422
    assert cliente.post("/usuarios", headers=hadm, json={**base, "rol": "Inexistente"}).status_code == 422
    assert cliente.post("/usuarios", headers=hadm, json={**base, "rol": "Corredor"}).status_code == 422          # corredor sin corredora
    r = cliente.post("/usuarios", headers=hadm, json=base)
    assert r.status_code == 201
    uid = r.get_json()["id"]
    assert cliente.post("/usuarios", headers=hadm, json=base).status_code == 409                                   # correo repetido
    assert cliente.put(f"/usuarios/{uid}", headers=hadm, json={"rol": "Administrador"}).status_code == 200
    assert cliente.put(f"/usuarios/{uid}", headers=hadm, json={"activo": False}).status_code == 200
    assert cliente.post("/login", json={"email": "prueba1@nuam.com", "password": "clave-larga-1"}).status_code == 401
    acciones = {x["accion"] for x in cliente.get("/log?accion=usuario", headers=hadm).get_json()}
    assert acciones >= {"Creación usuario", "Modificación usuario"}
