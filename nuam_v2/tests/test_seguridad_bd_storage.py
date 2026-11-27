"""Seguridad (RNF1), integridad de la base de datos (RNF2) y Object Storage."""
import datetime as dt
import os

import boto3
import jwt
import psycopg2
import psycopg2.errors
import pytest
from moto import mock_aws

import app as appmod
from conftest import crear, cuerpo, ids_instrumentos, listar, subir_pdf, pdf_texto
from storage import LocalStorage, S3Storage


# ---------------------------------------------------------------- seguridad
def test_S01_inyeccion_sql_neutralizada(cliente, ha):
    crear(cliente, ha)
    n = listar(cliente, ha)["total"]
    for payload in ("' OR 1=1 --", "'; DROP TABLE log_auditoria; --", "%' UNION SELECT NULL --"):
        r = cliente.get("/calificaciones", headers=ha, query_string={"instrumento": payload, "origen": payload, "mercado": payload})
        assert r.status_code == 200 and r.get_json()["total"] == 0
    assert listar(cliente, ha)["total"] == n                                            # la tabla sigue intacta


def test_S02_autenticacion_y_roles(cliente, ha, hb, haud, hadm):
    assert cliente.get("/calificaciones").status_code == 401
    assert cliente.get("/calificaciones", headers={"Authorization": "Bearer basura"}).status_code == 401
    assert cliente.post("/calificaciones", headers=haud, json={}).status_code == 403
    assert cliente.get("/usuarios", headers=ha).status_code == 403
    assert cliente.get("/log", headers=ha).status_code == 403
    assert cliente.get("/log", headers=haud).status_code == 200
    assert cliente.post("/login", json={"email": "a@corredora.cl", "password": "mala"}).status_code == 401
    assert cliente.post("/login", json={}).status_code == 401


def test_S03_token_expirado_o_manipulado(cliente):
    expirado = jwt.encode({"sub": "1", "rol": "Corredor", "corredor": 1, "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)}, appmod.SECRET, algorithm="HS256")
    falso = jwt.encode({"sub": "1", "rol": "Administrador", "corredor": None, "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)}, "otra-clave", algorithm="HS256")
    sin_firma = jwt.encode({"sub": "1", "rol": "Administrador"}, None, algorithm="none")
    for t in (expirado, falso, sin_firma):
        assert cliente.get("/usuarios", headers={"Authorization": "Bearer " + t}).status_code == 401


def test_S04_bloqueo_por_intentos_y_cabeceras(cliente):
    for _ in range(5):
        assert cliente.post("/login", json={"email": "auditor@nuam.com", "password": "x"}).status_code == 401
    assert cliente.post("/login", json={"email": "auditor@nuam.com", "password": "clave-auditor"}).status_code == 429
    appmod.FALLOS.clear()
    r = cliente.get("/")
    assert r.status_code == 200 and b"Mantenedor CORE" in r.data
    h = r.headers
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff" and "default-src 'self'" in h["Content-Security-Policy"]


def test_S05_aislamiento_entre_corredores(cliente, ha, hb):
    idc = crear(cliente, ha)
    assert cliente.get(f"/calificaciones/{idc}", headers=hb).status_code == 404
    assert cliente.put(f"/calificaciones/{idc}", headers=hb, json=cuerpo(cliente, hb)).status_code == 404
    assert cliente.delete(f"/calificaciones/{idc}", headers=hb).status_code == 404


def test_S06_errores_genericos_sin_detalles_tecnicos(cliente, ha):
    r = cliente.post("/calificaciones", headers=ha, data="esto no es json", content_type="application/json")
    assert r.status_code in (422, 400) and "Traceback" not in r.get_data(as_text=True) and "psycopg2" not in r.get_data(as_text=True)
    r = cliente.get("/ruta-inexistente", headers=ha)
    assert r.status_code == 404 and "Traceback" not in r.get_data(as_text=True)


def test_S07_entradas_hostiles_no_rompen_el_sistema(cliente, ha):
    for campo, valor in (("descripcion", "<script>alert(1)</script>" * 20), ("ejercicio", "2025; DROP TABLE x"), ("secuencia", "1e9"),
                         ("valor_historico", "9" * 50), ("id_instrumento", "abc"), ("id_instrumento", None)):
        r = cliente.post("/calificaciones", headers=ha, json=cuerpo(cliente, ha, **{campo: valor}))
        assert r.status_code in (201, 409, 422), (campo, r.status_code, r.get_json())
        assert r.status_code != 500


def test_S08_archivos_peligrosos(cliente, ha):
    assert subir_pdf(cliente, ha, b"MZ\x90\x00", "virus.pdf").status_code == 422
    assert subir_pdf(cliente, ha, pdf_texto(), "../../etc/passwd.pdf").status_code == 201        # el nombre original no se usa para guardar
    big = b"%PDF" + b"0" * (9 * 1024 * 1024)
    assert subir_pdf(cliente, ha, big).status_code == 413                                       # tamaño máximo


def test_S09_contrasenas_con_hash(bd):
    cur = bd.cursor()
    cur.execute("SELECT pass_hash FROM usuario")
    assert all(h.startswith(("scrypt:", "pbkdf2:")) and "clave-" not in h for (h,) in cur.fetchall())


# ---------------------------------------------------------------- integridad de la base de datos
def _ins_cal(cur, **kw):
    d = dict(id_corredor=1, id_instrumento=1, anio=2025, mercado="ACN", sec=1, origen="Manual")
    d.update(kw)
    cur.execute("INSERT INTO calificacion_tributaria(id_corredor,id_instrumento,anio_tributario,mercado,secuencia_evento,origen) "
                "VALUES (%(id_corredor)s,%(id_instrumento)s,%(anio)s,%(mercado)s,%(sec)s,%(origen)s) RETURNING id_calificacion", d)
    return cur.fetchone()[0]


def test_BD01_trigger_suma_8_a_19(cliente, bd):
    cur = bd.cursor()
    idc = _ins_cal(cur)
    cur.execute("INSERT INTO calificacion_valor VALUES (%s, 8, NULL, 0.5)", (idc,))
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("INSERT INTO calificacion_valor VALUES (%s, 9, NULL, 0.55)", (idc,))
    bd.rollback()


def test_BD02_factor_fuera_de_rango_y_numero_de_factor(cliente, bd):
    cur = bd.cursor()
    idc = _ins_cal(cur)
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("INSERT INTO calificacion_valor VALUES (%s, 20, NULL, 1.5)", (idc,))
    bd.rollback()
    cur = bd.cursor()
    idc = _ins_cal(cur)
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cur.execute("INSERT INTO calificacion_valor VALUES (%s, 38, NULL, 0.1)", (idc,))
    bd.rollback()


def test_BD03_log_inmutable(cliente, ha, bd):
    crear(cliente, ha)
    cur = bd.cursor()
    for sql in ("UPDATE log_auditoria SET accion = 'x'", "DELETE FROM log_auditoria"):
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute(sql)
        bd.rollback()
        cur = bd.cursor()


def test_BD04_llave_unica_y_reglas_de_origen(cliente, bd):
    cur = bd.cursor()
    _ins_cal(cur)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _ins_cal(cur)
    bd.rollback()
    cur = bd.cursor()
    with pytest.raises(psycopg2.errors.CheckViolation):          # un corredor no puede registrar origen Sistema/Bolsa
        _ins_cal(cur, origen="Sistema/Bolsa")
    bd.rollback()
    cur = bd.cursor()
    with pytest.raises(psycopg2.errors.CheckViolation):          # la Bolsa (sin corredor) solo con origen Sistema/Bolsa
        _ins_cal(cur, id_corredor=None, origen="Manual")
    bd.rollback()


def test_BD05_borrar_calificacion_borra_sus_valores(cliente, ha, bd):
    idc = crear(cliente, ha)
    cur = bd.cursor()
    cur.execute("SELECT count(*) FROM calificacion_valor WHERE id_calificacion = %s", (idc,))
    assert cur.fetchone()[0] == 4
    cliente.delete(f"/calificaciones/{idc}", headers=ha)
    cur.execute("SELECT count(*) FROM calificacion_valor WHERE id_calificacion = %s", (idc,))
    assert cur.fetchone()[0] == 0


def test_BD06_los_indices_existen(bd):
    cur = bd.cursor()
    cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    nombres = {r[0] for r in cur.fetchall()}
    assert {"ux_calificacion_llave", "ix_cal_corredor_filtros", "ix_cal_instrumento", "ix_cal_origen", "ix_log_ts", "ix_cert_corredor"} <= nombres


def test_BD07_la_consulta_principal_usa_indice(bd):
    cur = bd.cursor()
    cur.execute("SET enable_seqscan = off")
    cur.execute("EXPLAIN SELECT * FROM calificacion_tributaria WHERE id_corredor = 1 AND anio_tributario = 2025 AND mercado = 'ACN'")
    assert "Index" in "\n".join(r[0] for r in cur.fetchall())


# ---------------------------------------------------------------- Object Storage
def test_ST01_storage_local(tmp_path):
    s = LocalStorage(str(tmp_path))
    s.put("cert_abc.pdf", b"%PDF-1")
    assert s.get("cert_abc.pdf") == b"%PDF-1" and s.existe("cert_abc.pdf") and not s.existe("cert_zzz.pdf")


@pytest.mark.parametrize("clave", ["../x.pdf", "a/b.pdf", "x.exe", "", "x.pdf/../../y"])
def test_ST02_claves_invalidas(tmp_path, clave):
    with pytest.raises(ValueError):
        LocalStorage(str(tmp_path)).put(clave, b"x")


def test_ST03_storage_s3_en_la_nube_simulada(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="nuam-certificados")
        s = S3Storage("nuam-certificados")
        s.put("cert_abc.pdf", b"%PDF-1", "application/pdf")
        assert s.get("cert_abc.pdf") == b"%PDF-1" and s.existe("cert_abc.pdf") and not s.existe("cert_no.pdf")
        head = boto3.client("s3", region_name="us-east-1").head_object(Bucket="nuam-certificados", Key="cert_abc.pdf")
        assert head["ServerSideEncryption"] == "AES256"                                          # cifrado en reposo
        with pytest.raises(ValueError):
            s.put("../x.pdf", b"x")
