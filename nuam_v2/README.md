# Nuam · Mantenedor CORE Web de Calificaciones Tributarias

Aplicación web para que las corredoras de Nuam Exchange (Chile, Perú, Colombia) ingresen, calculen, carguen masivamente y homologuen
calificaciones tributarias (factores 8 al 37), con auditoría inmutable y control de acceso por rol.
Proyecto INACAP · Caso Nuam · Equipo: Carla Caro y Manuel Montecinos.

## 1. Arquitectura (modelo 4+1 resumido)
```
Navegador (HTML/CSS/JS, sin frameworks)
   │  HTTPS + JWT (15 min)
Flask API (app.py)  ── core.py (reglas de cálculo y validación)
   │                ── homologacion.py (PDF → texto/OCR → columnas → factores)
   │                ── storage.py (Object Storage: carpeta local o S3 con cifrado AES256)
PostgreSQL 16 (schema.sql: 3FN, triggers de integridad, log inmutable)
```
| Capa | Tecnología | Archivo |
|---|---|---|
| Frontend | HTML5, CSS, JavaScript ES2020 | `static/` |
| Backend | Python 3.12+, Flask, PyJWT, Gunicorn | `app.py`, `core.py` |
| BD estructurada | PostgreSQL 16 | `schema.sql` |
| BD no estructurada | Object Storage (PDF originales + JSON de extracción) y JSONB (`extraccion`, `log_auditoria.detalle`) | `storage.py` |
| OCR / IDP | pypdf (texto) + pdftoppm + Tesseract (spa+eng) para escaneados | `homologacion.py` |

## 2. Instalación paso a paso
**Requisitos del sistema:** Python 3.12+, PostgreSQL 16, `poppler-utils`, `tesseract-ocr`, `tesseract-ocr-spa`.
```bash
# Ubuntu/Debian
sudo apt install postgresql postgresql-client poppler-utils tesseract-ocr tesseract-ocr-spa
# Windows: instalar PostgreSQL, Tesseract (UB-Mannheim, marcar español) y Poppler; agregarlos al PATH
```
1. `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
2. `pip install -r requirements.txt`
3. Crear la base y cargar datos de ejemplo (automático):
   `python instalar.py --dsn "host=localhost port=5432 user=postgres password=TU_CLAVE" --bd nuam`
   (use `--sin-datos` para instalar sin usuarios ni calificaciones de ejemplo).
4. Variables de entorno (ver `.env.example`):
   `export NUAM_DSN="host=localhost port=5432 dbname=nuam user=postgres password=TU_CLAVE"`
5. Ejecutar: `gunicorn -w 4 --threads 8 -b 0.0.0.0:8080 app:app` y abrir <http://localhost:8080>
   (desarrollo rápido: `python app.py`).
6. Verificar: `NUAM_DSN=... pytest tests -q` → 88 pruebas deben pasar.

**Usuarios de ejemplo:** `a@corredora.cl / clave-a` (Corredor A, Chile) · `b@corredora.pe / clave-b` (Corredor B, Perú) ·
`admin@nuam.com / clave-admin` · `auditor@nuam.com / clave-auditor`. **Cámbielos antes de cualquier uso real.**

**Producción:** `NUAM_ENV=produccion` exige `JWT_SECRET` (≥32 caracteres aleatorios). Poner un proxy con TLS 1.2+ delante (nginx/ALB);
la base y el bucket cifrados en reposo (AES-256: `NUAM_STORAGE=s3`, `NUAM_S3_BUCKET=...`, SSE AES256 ya activado en `S3Storage`).

**Docker (no probado en el entorno de desarrollo):** `cp .env.example .env && docker compose up --build`, luego
`docker compose exec api python instalar.py --dsn "host=bd user=postgres password=postgres"`.

## 3. Reglas de negocio implementadas
- Factor = monto de la columna / suma de montos de las columnas 8 a 19, redondeado half-up a 8 decimales.
- Cada factor entre 0 y 1; la suma de factores 8–19 no puede superar 1 (tolerancia 0,00000006 por redondeo de 12 columnas). Validado en `core.py` **y** por trigger en la BD.
- 30 factores (8 al 37). Ingreso por montos o directo por factores.
- Llave de una calificación: corredora + ejercicio + mercado + instrumento + secuencia. La carga masiva crea si no existe y actualiza si existe.
- Información de la Bolsa (`id_corredor` NULL, origen *Sistema/Bolsa*) es visible a todas las corredoras; la versión propia de la corredora **prima** sobre la de la Bolsa; editar una de la Bolsa crea una copia local y la original no se toca; la Bolsa no se puede eliminar.
- Instrumentos no inscritos creados por una corredora son locales a ella.
- Origen de cada registro: Manual, Carga masiva montos, Carga masiva factores, Certificado, Sistema/Bolsa.
- Cada ingreso, edición, eliminación, carga y alta de usuario queda en el log (antes/después), imposible de modificar o borrar (trigger).

## 4. Modelo de datos y normalización
Ver `docs/DICCIONARIO_DATOS.md`. Resumen: 3FN; los 30 factores viven en la tabla hija `calificacion_valor (id_calificacion, nro_factor, monto, factor)` en vez de 30 columnas
repetidas (1FN/2FN); catálogos (`rol`, `mercado`, `origen`, `factor_catalogo`) con claves foráneas; JSONB solo donde el dato es semiestructurado (extracción del certificado, detalle del log); PDF en Object Storage con hash SHA-256.
Índices: llave única parcial de calificaciones, `(id_corredor, anio_tributario, mercado)` para el listado, instrumento, origen, `log(ts)` y `certificado(id_corredor)`; `EXPLAIN` verificado en pruebas (BD07).

## 5. Seguridad (RNF1)
Contraseñas con hash (scrypt) · JWT con expiración 15 min · RBAC (Corredor / Administrador / Auditor) en cada endpoint ·
consultas 100 % parametrizadas (prueba de inyección SQL S01) · bloqueo tras 5 intentos fallidos en 5 min (HTTP 429) ·
cabeceras CSP, X-Frame-Options, nosniff, Referrer-Policy, Cache-Control no-store · mensajes de error genéricos ·
validación de claves de storage, firma/tamaño de archivos (PDF ≤ 8 MB) · aislamiento entre corredoras · log inmutable.

## 6. API (resumen)
| Método y ruta | Rol | Descripción |
|---|---|---|
| POST `/login` | — | Token JWT |
| GET `/catalogos`, `/instrumentos` · POST `/instrumentos` | todos / Corredor | Catálogos; alta de instrumento no inscrito |
| GET `/calificaciones` (mercado, origen, fuente, anio, instrumento, pagina, tam) · GET `/calificaciones/<id>` | todos | Búsqueda paginada y detalle |
| POST `/calificaciones/calcular` | Corredor | Calcula factores sin grabar |
| POST `/calificaciones` · PUT/DELETE `/calificaciones/<id>` | Corredor | Ingreso, modificación (copia local si es Bolsa), eliminación |
| GET `/plantilla?tipo=montos\|factores` · POST `/calificaciones/csv?tipo=&modo=previsualizar\|confirmar` | Corredor | Carga masiva |
| POST `/certificados` · GET `/certificados/<uuid>/archivo` | Corredor / todos | Homologación IDP/OCR; descarga del original |
| `/usuarios` (GET, POST, PUT) | Administrador | Gestión de usuarios |
| GET `/log?accion=` | Administrador, Auditor | Auditoría |

## 7. Pruebas y resultados
`tests/` (88 casos): unitarias del cálculo, API trazada a RF1–RF13, reglas Bolsa/corredor, carga masiva, OCR, seguridad, BD y storage S3 (moto).
`perf_test.py`: 500 filas + 50 usuarios, y estrés de 5.000 filas + 200 usuarios; resultados en `resultados_rendimiento.txt`. Matriz de trazabilidad: `docs/TRAZABILIDAD_RF.md`.

## 8. Limitaciones conocidas (honestidad técnica)
- La **homologación de columnas** de Certificado 70/44 y DJ 1948/1922 viene con un mapeo identidad (columna N → factor N) hasta contar con el mapeo oficial de Nuam; es configurable en la tabla `homologacion_columna` sin tocar código.
- Los nombres de factores son genéricos ("Factor N"); se reemplazan en `factor_catalogo`.
- El bloqueo de login es por proceso de Gunicorn (en memoria); para varios servidores usar Redis.
- El enunciado habla de "29 factores" y las columnas 8–37 son 30; se implementaron 30.
- La prueba de usabilidad con usuarios reales está pendiente de ejecución por el equipo.
