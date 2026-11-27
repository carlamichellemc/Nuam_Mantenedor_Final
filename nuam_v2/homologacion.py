"""IDP/OCR: extrae el texto de un certificado PDF (con OCR si está escaneado), lo interpreta y homologa
las columnas del formato de origen (Certificado 70 / DJ 1948, Certificado 44 / DJ 1922) a los factores internos."""
import io
import os
import re
import shutil
import subprocess
import tempfile

from pypdf import PdfReader

from core import NROS, ErrorValidacion, parsear_numero

MIN_TEXTO = 25     # menos caracteres que esto => se considera PDF escaneado y se aplica OCR


def _ocr(pdf_bytes):
    """Rasteriza el PDF con pdftoppm y lee cada página con Tesseract."""
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        raise ErrorValidacion("El PDF es una imagen y requiere OCR, pero Tesseract/Poppler no están instalados en el servidor")
    idioma = "spa+eng" if "spa" in subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout else "eng"
    with tempfile.TemporaryDirectory() as tmp:
        pdf = os.path.join(tmp, "doc.pdf")
        with open(pdf, "wb") as f:
            f.write(pdf_bytes)
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-png", "-l", "20", pdf, os.path.join(tmp, "p")], check=True, timeout=120)
        textos = []
        for img in sorted(x for x in os.listdir(tmp) if x.startswith("p") and x.endswith(".png")):
            r = subprocess.run(["tesseract", os.path.join(tmp, img), "stdout", "-l", idioma, "--psm", "6"],
                               capture_output=True, text=True, timeout=120)
            textos.append(r.stdout)
    return "\n".join(textos)


def extraer_texto(pdf_bytes):
    """Devuelve (texto, ocr_usado)."""
    try:
        texto = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        raise ErrorValidacion("No se pudo leer el PDF")
    if len(texto.strip()) >= MIN_TEXTO:
        return texto, False
    return _ocr(pdf_bytes), True


_NUM = r"(\d[\d.,]*)"
_PATRONES = {
    "ejercicio": r"(?:ejercicio|a[nñ]o\s+tributario)\s*[:=]?\s*(\d{4})",
    "mercado": r"mercado\s*[:=]?\s*(ACN|CFI|FMU)",
    "instrumento": r"instrumento\s*[:=]?\s*([^\n\r]+)",
    "secuencia": r"secuencia(?:\s+de\s+evento)?\s*[:=]?\s*(\d+)",
    "numero_dividendo": r"(?:n[uú]mero\s+de\s+dividendo|dividendo)\s*[:=]?\s*(\d+)",
    "fecha_pago": r"fecha(?:\s+de\s+pago)?\s*[:=]?\s*(\d{2}[-/]\d{2}[-/]\d{4})",
    "valor_historico": r"valor\s+hist[oó]rico\s*[:=]?\s*" + _NUM,
    "tipo_sociedad": r"tipo\s+(?:de\s+)?sociedad\s*[:=]?\s*([AC])\b",
}


def parsear_certificado(texto):
    """Interpreta el texto: tipo de certificado, datos base y columnas con su valor."""
    t = re.search(r"certificado\s*(?:n[°ºo.]*\s*)?(70|44)\b", texto, re.I)
    tipo = t.group(1) if t else None
    if not tipo:
        d = re.search(r"\bDJ\s*(1948|1922)\b", texto, re.I)
        tipo = {"1948": "70", "1922": "44"}.get(d.group(1)) if d else None
    if not tipo:
        raise ErrorValidacion("No se reconoce el tipo de certificado (Certificado 70 / DJ 1948 o Certificado 44 / DJ 1922)")
    datos = {"tipo": tipo}
    for campo, rx in _PATRONES.items():
        m = re.search(rx, texto, re.I)
        if m:
            datos[campo] = m.group(1).strip()
    columnas = {}
    for m in re.finditer(r"(?:columna|col\.?|factor|monto)\s*[_ ]?\s*(\d{1,2})\s*[:=]\s*" + _NUM, texto, re.I):
        n = int(m.group(1))
        if n in NROS:
            columnas[n] = m.group(2).rstrip(".,")
    if not columnas:
        raise ErrorValidacion("No se encontraron columnas de montos en el certificado")
    datos["columnas"] = columnas
    return datos


def homologar(columnas, mapa):
    """columnas: {columna_origen: texto}; mapa: {columna_origen: nro_factor}. Devuelve {nro_factor: Decimal}."""
    montos, sin_mapeo = {}, []
    for col, valor in columnas.items():
        nro = mapa.get(int(col))
        if nro is None:
            sin_mapeo.append(col)
            continue
        montos[nro] = parsear_numero(valor, f"Columna {col}")
    return montos, sin_mapeo
