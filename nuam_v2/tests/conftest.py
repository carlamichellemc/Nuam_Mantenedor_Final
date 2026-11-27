import io
import os
import sys

import psycopg2
import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as appmod  # noqa: E402

DSN = os.environ.get("NUAM_DSN", "host=localhost port=5432 dbname=nuam user=postgres password=postgres")


@pytest.fixture()
def cliente():
    """Cliente HTTP con la base limpia de datos de corredores (se conservan catálogos, usuarios y calificaciones de la Bolsa)."""
    c = psycopg2.connect(DSN)
    cur = c.cursor()
    cur.execute("TRUNCATE log_auditoria RESTART IDENTITY")
    cur.execute("DELETE FROM calificacion_tributaria WHERE id_corredor IS NOT NULL")
    cur.execute("DELETE FROM certificado")
    cur.execute("DELETE FROM instrumento WHERE id_corredor_creador IS NOT NULL")
    cur.execute("DELETE FROM usuario WHERE email LIKE 'prueba%'")
    cur.execute("DELETE FROM homologacion_columna WHERE tipo_certificado = '44'")
    cur.execute("INSERT INTO homologacion_columna SELECT '44', n, n FROM generate_series(8, 37) n")
    c.commit()
    c.close()
    appmod.FALLOS.clear()
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


@pytest.fixture()
def bd():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def token(cl, email, pw):
    return {"Authorization": "Bearer " + cl.post("/login", json={"email": email, "password": pw}).get_json()["token"]}


@pytest.fixture()
def ha(cliente):
    return token(cliente, "a@corredora.cl", "clave-a")


@pytest.fixture()
def hb(cliente):
    return token(cliente, "b@corredora.pe", "clave-b")


@pytest.fixture()
def hadm(cliente):
    return token(cliente, "admin@nuam.com", "clave-admin")


@pytest.fixture()
def haud(cliente):
    return token(cliente, "auditor@nuam.com", "clave-auditor")


def ids_instrumentos(cl, h):
    return {i["codigo"]: i["id_instrumento"] for i in cl.get("/instrumentos", headers=h).get_json()}


def cuerpo(cl, h, **kw):
    """Cuerpo válido para crear una calificación (se puede sobrescribir cualquier campo)."""
    d = {"ejercicio": 2025, "mercado": "ACN", "id_instrumento": ids_instrumentos(cl, h)["COPEC"], "secuencia": 100,
         "numero_dividendo": 1, "tipo_sociedad": "A", "fecha_pago": "15-04-2025", "valor_historico": "1250.50",
         "descripcion": "Dividendo de prueba", "isfut": False, "factor_actualizacion": "1.02", "modo": "montos",
         "valores": {"8": 400000, "9": 350000, "10": 250000, "20": 100000}}
    d.update(kw)
    return d


def crear(cl, h, **kw):
    r = cl.post("/calificaciones", headers=h, json=cuerpo(cl, h, **kw))
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def listar(cl, h, **q):
    return cl.get("/calificaciones", headers=h, query_string=q).get_json()


def pdf_texto(tipo="70", extra=None, instrumento="COPEC"):
    lineas = [f"Certificado {tipo} - Sobre situacion tributaria", "Ejercicio: 2025", "Mercado: ACN", f"Instrumento: {instrumento}",
              "Secuencia: 500", "Numero de dividendo: 77", "Fecha de pago: 15-04-2025", "Valor historico: 1.250,50",
              "Columna 8: 400.000", "Columna 9: 350.000", "Columna 10: 250.000", "Columna 20: 100.000"] + (extra or [])
    buf = io.BytesIO()
    p = canvas.Canvas(buf)
    for i, l in enumerate(lineas):
        p.drawString(72, 790 - 18 * i, l)
    p.save()
    return buf.getvalue()


def pdf_escaneado():
    """PDF que solo contiene una imagen (como un certificado escaneado): obliga a usar OCR."""
    for ruta in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        if os.path.exists(ruta):
            fuente = ImageFont.truetype(ruta, 44)
            break
    else:
        fuente = ImageFont.load_default(size=44)
    img = Image.new("L", (1654, 2339), 255)
    d = ImageDraw.Draw(img)
    lineas = ["Certificado 70", "Ejercicio: 2025", "Mercado: ACN", "Instrumento: COPEC", "Secuencia: 600",
              "Columna 8: 400000", "Columna 9: 350000", "Columna 10: 250000"]
    for i, l in enumerate(lineas):
        d.text((120, 150 + 90 * i), l, fill=0, font=fuente)
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=200)
    return buf.getvalue()


def subir_pdf(cl, h, datos, nombre="cert.pdf"):
    return cl.post("/certificados", headers=h, data={"archivo": (io.BytesIO(datos), nombre)}, content_type="multipart/form-data")


def csv_montos(filas, delim=";"):
    cab = ["Ejercicio", "Mercado", "Instrumento", "Fecha", "Secuencia", "Numero_dividendo", "Tipo_sociedad", "Valor_historico",
           "Monto_8", "Monto_9", "Monto_10", "Monto_20"]
    return "\n".join([delim.join(cab)] + [delim.join(str(x) for x in f) for f in filas]) + "\n"


def subir_csv(cl, h, texto, tipo="montos", modo="previsualizar", nombre="lote.csv"):
    return cl.post(f"/calificaciones/csv?tipo={tipo}&modo={modo}", headers=h,
                   data={"archivo": (io.BytesIO(texto.encode()), nombre)}, content_type="multipart/form-data")
