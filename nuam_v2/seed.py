"""Datos iniciales: corredoras, instrumentos de la Bolsa, usuarios de prueba y calificaciones de la Bolsa."""
import os
import psycopg2
from werkzeug.security import generate_password_hash as h
import core

DSN = os.environ.get("NUAM_DSN", "host=localhost port=5432 dbname=nuam user=postgres password=postgres")
c = psycopg2.connect(DSN)
cur = c.cursor()
cur.execute("INSERT INTO corredor(razon_social, pais) VALUES ('Corredora A', 'Chile'), ('Corredora B', 'Perú')")
cur.execute("""INSERT INTO instrumento(codigo, nombre_emisor, pais_emisor, mercado) VALUES
  ('COPEC', 'Empresas Copec', 'Chile', 'ACN'), ('BCO-SAN', 'Banco Santander Chile', 'Chile', 'ACN'),
  ('ENELCHILE', 'Enel Chile', 'Chile', 'ACN'), ('CMPC', 'Empresas CMPC', 'Chile', 'ACN'),
  ('CFI-RENTA', 'Fondo de Inversión Renta Inmobiliaria', 'Chile', 'CFI'), ('FM-DEUDA', 'Fondo Mutuo Deuda Corto Plazo', 'Chile', 'FMU')""")
cur.execute("""INSERT INTO usuario(nombre, email, pass_hash, id_rol, id_corredor, pais) VALUES
  ('Corredor A', 'a@corredora.cl', %s, 1, 1, 'Chile'), ('Corredor B', 'b@corredora.pe', %s, 1, 2, 'Perú'),
  ('Administrador', 'admin@nuam.com', %s, 2, NULL, 'Chile'), ('Auditor', 'auditor@nuam.com', %s, 3, NULL, 'Chile')""",
            (h("clave-a"), h("clave-b"), h("clave-admin"), h("clave-auditor")))
# Calificaciones de la Bolsa (origen Sistema/Bolsa, sin corredor): los corredores las ven pero no las alteran
bolsa = [(2025, 'ACN', 1, 9001, '2025-04-15', 'Dividendo definitivo 2024', {8: 40000000, 9: 35000000, 10: 25000000, 20: 5000000}),
         (2025, 'ACN', 2, 9002, '2025-05-20', 'Dividendo provisorio 2025', {8: 80000000, 9: 20000000, 21: 1000000}),
         (2024, 'ACN', 3, 9003, '2024-12-10', 'Dividendo eventual', {8: 50000000, 9: 50000000}),
         (2025, 'CFI', 5, 9004, '2025-06-30', 'Reparto de beneficios', {8: 60000000, 9: 40000000}),
         (2025, 'FMU', 6, 9005, '2025-03-31', 'Rescate con crédito', {8: 70000000, 10: 30000000})]
for ej, mer, ins, sec, fecha, desc, montos in bolsa:
    m, f = core.calcular_desde_montos(montos)
    cur.execute("""INSERT INTO calificacion_tributaria(id_corredor, id_instrumento, anio_tributario, mercado, secuencia_evento, fecha_pago, descripcion,
                   origen, forma_modificacion) VALUES (NULL, %s, %s, %s, %s, %s, %s, 'Sistema/Bolsa', 'Carga de la Bolsa') RETURNING id_calificacion""",
                (ins, ej, mer, sec, fecha, desc))
    idc = cur.fetchone()[0]
    for n, fac in f.items():
        cur.execute("INSERT INTO calificacion_valor VALUES (%s, %s, %s, %s)", (idc, n, m[n], fac))
c.commit()
print("seed ok")
