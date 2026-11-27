"""Pruebas de rendimiento y estrés (RNF: 500 registros por carga, 50 usuarios concurrentes, búsquedas < 3 s).
Uso: NUAM_URL=http://127.0.0.1:8081 NUAM_DSN=... python perf_test.py [filas_estres] [usuarios_estres]"""
import concurrent.futures as cf, csv, io, os, statistics, sys, time
import psycopg2, requests

B = os.environ.get("NUAM_URL", "http://127.0.0.1:8081")
DSN = os.environ.get("NUAM_DSN", "host=localhost port=5432 dbname=nuam user=postgres password=postgres")
FILAS_E, USR_E = int(sys.argv[1]) if len(sys.argv) > 1 else 5000, int(sys.argv[2]) if len(sys.argv) > 2 else 200
c = psycopg2.connect(DSN); c.autocommit = True; cur = c.cursor()
cur.execute("DELETE FROM calificacion_tributaria WHERE id_corredor IS NOT NULL"); cur.execute("DELETE FROM certificado")
H = {"Authorization": "Bearer " + requests.post(B + "/login", json={"email": "a@corredora.cl", "password": "clave-a"}).json()["token"]}
INSTR = ["Copec", "BCO-SAN", "ENELCHILE", "CMPC"]


def csv_filas(n, desde=0):
    b = io.StringIO(); w = csv.writer(b, delimiter=";")
    w.writerow(["Ejercicio", "Mercado", "Instrumento", "Fecha", "Secuencia", "Numero_dividendo", "Tipo_sociedad", "Valor_historico"] + [f"Monto_{k}" for k in range(8, 38)])
    for i in range(desde, desde + n):
        w.writerow([2000 + i % 90, "ACN", INSTR[i % 4], "15-04-2025", 100000 + i, 1, "A", "1250.5"] + [1000 + i % 7 if k < 20 else 10 for k in range(8, 38)])
    return b.getvalue()


def carga(n, desde=0):
    t = time.perf_counter()
    r = requests.post(B + "/calificaciones/csv?tipo=montos&modo=confirmar", headers=H, files={"archivo": ("lote.csv", csv_filas(n, desde))}, timeout=300)
    return r.status_code, time.perf_counter() - t


def concurrentes(usuarios, consultas=4):
    def usuario(_):
        out = []
        for q in ("BCO", "ENE", "CMPC", "COP")[:consultas]:
            t = time.perf_counter()
            rr = requests.get(B + "/calificaciones", params={"instrumento": q, "tam": 25}, headers=H, timeout=60)
            out.append((rr.status_code, time.perf_counter() - t))
        return out
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(usuarios) as ex:
        res = [x for l in ex.map(usuario, range(usuarios)) for x in l]
    ts = sorted(t for _, t in res)
    return len(res), time.perf_counter() - t0, sum(s != 200 for s, _ in res), statistics.mean(ts), ts[int(len(ts) * .95)], ts[-1]


print("== R1: carga de 500 filas (30 factores cada una) + 50 usuarios concurrentes ==")
s, t = carga(500)
cur.execute("SELECT count(*) FROM calificacion_tributaria WHERE id_corredor IS NOT NULL"); n = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM calificacion_valor v JOIN calificacion_tributaria c USING(id_calificacion) WHERE c.id_corredor IS NOT NULL"); nv = cur.fetchone()[0]
print(f"Carga CSV 500 filas: HTTP {s} en {t:.2f} s | filas en BD: {n} | valores de factores: {nv}")
p, d, e, m, p95, mx = concurrentes(50)
print(f"50 usuarios x 4 búsquedas = {p} peticiones en {d:.2f} s | errores {e} | media {m:.3f} s | p95 {p95:.3f} s | máx {mx:.3f} s")
print("RESULTADO R1:", "PASÓ" if (s == 201 and n == 500 and nv == 500 * 30 and e == 0 and mx < 3) else "FALLÓ")

print(f"\n== ESTRÉS: carga de {FILAS_E} filas adicionales + {USR_E} usuarios concurrentes ==")
s, t = carga(FILAS_E, 500)
cur.execute("SELECT count(*) FROM calificacion_tributaria WHERE id_corredor IS NOT NULL"); n = cur.fetchone()[0]
print(f"Carga CSV {FILAS_E} filas: HTTP {s} en {t:.2f} s | total en BD: {n}")
p, d, e, m, p95, mx = concurrentes(USR_E)
print(f"{USR_E} usuarios x 4 búsquedas = {p} peticiones en {d:.2f} s | errores {e} | media {m:.3f} s | p95 {p95:.3f} s | máx {mx:.3f} s")
cur.execute("SELECT count(*) FROM log_auditoria"); print("Registros de auditoría:", cur.fetchone()[0])
print("RESULTADO ESTRÉS:", "PASÓ (sin caídas ni errores)" if (s == 201 and e == 0) else "FALLÓ")
