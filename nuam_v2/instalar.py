#!/usr/bin/env python3
"""Instalador: crea la base de datos, aplica schema.sql, carga datos de ejemplo y verifica dependencias.
Uso: python instalar.py [--sin-datos] [--dsn "host=... port=... user=... password=..."] [--bd nuam]"""
import argparse, os, shutil, subprocess, sys

import psycopg2
from psycopg2 import sql

AQUI = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--dsn", default="host=localhost port=5432 user=postgres password=postgres", help="conexión SIN dbname")
ap.add_argument("--bd", default="nuam")
ap.add_argument("--sin-datos", action="store_true", help="no cargar corredoras, usuarios ni calificaciones de ejemplo")
a = ap.parse_args()

print("1/4 Verificando herramientas del sistema")
for exe, para in (("pdftoppm", "OCR de certificados escaneados (paquete poppler-utils)"), ("tesseract", "OCR (paquete tesseract-ocr y tesseract-ocr-spa)")):
    print(f"   {'OK ' if shutil.which(exe) else 'FALTA'} {exe} - {para}")

print("2/4 Creando la base de datos", a.bd)
c = psycopg2.connect(a.dsn + " dbname=postgres"); c.autocommit = True
cur = c.cursor(); cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (a.bd,))
if cur.fetchone():
    print("   ya existe; se recrearán sus tablas (se pierden los datos previos)")
else:
    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(a.bd)))
c.close()

dsn = f"{a.dsn} dbname={a.bd}"
print("3/4 Aplicando schema.sql (tablas, índices, triggers)")
c = psycopg2.connect(dsn); c.autocommit = True
c.cursor().execute(open(os.path.join(AQUI, "schema.sql"), encoding="utf-8").read()); c.close()

print("4/4", "Omitiendo datos de ejemplo" if a.sin_datos else "Cargando datos de ejemplo")
if not a.sin_datos:
    subprocess.run([sys.executable, os.path.join(AQUI, "seed.py")], check=True, env={**os.environ, "NUAM_DSN": dsn})
os.makedirs(os.path.join(AQUI, "data", "storage"), exist_ok=True)
print(f"\nListo. Inicie con:\n  NUAM_DSN=\"{dsn}\" gunicorn -w 4 --threads 8 -b 0.0.0.0:8080 app:app\nY abra http://localhost:8080")
