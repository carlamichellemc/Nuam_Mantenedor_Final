-- =====================================================================
-- Mantenedor CORE de Calificaciones Tributarias · Nuam Exchange
-- Esquema PostgreSQL (3FN). Se puede ejecutar varias veces (reinicia el esquema).
-- =====================================================================
DROP TABLE IF EXISTS log_auditoria, calificacion_valor, calificacion_tributaria, homologacion_columna,
                     factor_catalogo, certificado, instrumento, origen, mercado, usuario, corredor, rol CASCADE;
DROP FUNCTION IF EXISTS bloquear_cambios_log() CASCADE;
DROP FUNCTION IF EXISTS validar_suma_factores() CASCADE;

-- ---------- Seguridad y usuarios ----------
CREATE TABLE rol (
  id_rol    SMALLINT PRIMARY KEY,
  nombre_rol TEXT UNIQUE NOT NULL
);
CREATE TABLE corredor (
  id_corredor  SERIAL PRIMARY KEY,
  razon_social TEXT NOT NULL,
  pais         TEXT NOT NULL CHECK (pais IN ('Chile', 'Perú', 'Colombia'))
);
CREATE TABLE usuario (
  id_usuario  SERIAL PRIMARY KEY,
  nombre      TEXT NOT NULL,
  email       TEXT UNIQUE NOT NULL,
  pass_hash   TEXT NOT NULL,
  activo      BOOLEAN NOT NULL DEFAULT TRUE,
  id_rol      SMALLINT NOT NULL REFERENCES rol,
  id_corredor INT REFERENCES corredor,
  pais        TEXT,
  CONSTRAINT corredor_requiere_corredora CHECK (id_rol <> 1 OR id_corredor IS NOT NULL)   -- rol 1 = Corredor
);

-- ---------- Catálogos (evitan texto libre y redundancia) ----------
CREATE TABLE mercado (
  codigo CHAR(3) PRIMARY KEY,
  nombre TEXT NOT NULL
);
CREATE TABLE origen (
  codigo TEXT PRIMARY KEY,
  fuente TEXT NOT NULL CHECK (fuente IN ('Corredor', 'Entidad prestadora'))
);
CREATE TABLE factor_catalogo (
  nro_factor SMALLINT PRIMARY KEY CHECK (nro_factor BETWEEN 8 AND 37),
  nombre     TEXT NOT NULL,
  concepto   TEXT NOT NULL
);

-- ---------- Instrumentos (inscritos de la Bolsa y no inscritos creados por un corredor) ----------
CREATE TABLE instrumento (
  id_instrumento     SERIAL PRIMARY KEY,
  codigo             TEXT NOT NULL,
  nombre_emisor      TEXT,
  pais_emisor        TEXT,
  mercado            CHAR(3) NOT NULL REFERENCES mercado,
  inscrito           BOOLEAN NOT NULL DEFAULT TRUE,
  id_corredor_creador INT REFERENCES corredor,          -- NULL = instrumento de la Bolsa
  CONSTRAINT no_inscrito_tiene_creador CHECK (inscrito OR id_corredor_creador IS NOT NULL)
);
CREATE UNIQUE INDEX ux_instrumento_codigo ON instrumento (upper(codigo), COALESCE(id_corredor_creador, 0));

-- ---------- Certificados (metadatos; el PDF original y su extracción JSON van al Object Storage) ----------
CREATE TABLE certificado (
  id_certificado UUID PRIMARY KEY,
  id_corredor    INT NOT NULL REFERENCES corredor,
  tipo           TEXT NOT NULL CHECK (tipo IN ('70', '44')),
  archivo        TEXT NOT NULL,            -- clave del PDF en el Object Storage
  archivo_json   TEXT NOT NULL,            -- clave de la extracción JSON en el Object Storage
  sha256         TEXT NOT NULL,
  ocr_usado      BOOLEAN NOT NULL DEFAULT FALSE,
  extraccion     JSONB,                    -- copia consultable de lo extraído (modelo híbrido)
  fecha_carga    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_cert_corredor ON certificado (id_corredor, fecha_carga DESC);

-- Homologación de columnas: columna del formato de origen -> factor interno único
CREATE TABLE homologacion_columna (
  tipo_certificado TEXT NOT NULL CHECK (tipo_certificado IN ('70', '44')),
  columna_origen   SMALLINT NOT NULL,
  nro_factor       SMALLINT NOT NULL REFERENCES factor_catalogo,
  PRIMARY KEY (tipo_certificado, columna_origen)
);

-- ---------- Calificaciones ----------
CREATE TABLE calificacion_tributaria (
  id_calificacion    SERIAL PRIMARY KEY,
  id_corredor        INT REFERENCES corredor,           -- NULL = calificación de la Bolsa (Nuam)
  id_instrumento     INT NOT NULL REFERENCES instrumento,
  anio_tributario    SMALLINT NOT NULL CHECK (anio_tributario BETWEEN 2000 AND 2100),   -- Ejercicio
  mercado            CHAR(3) NOT NULL REFERENCES mercado,
  secuencia_evento   INTEGER NOT NULL CHECK (secuencia_evento >= 0),
  numero_dividendo   INTEGER CHECK (numero_dividendo >= 0),
  tipo_sociedad      CHAR(1) CHECK (tipo_sociedad IN ('A', 'C')),                    -- Abierta / Cerrada
  fecha_pago         DATE,
  valor_historico    NUMERIC(18,2) CHECK (valor_historico >= 0),
  descripcion        VARCHAR(200),
  isfut              BOOLEAN NOT NULL DEFAULT FALSE,
  factor_actualizacion NUMERIC(10,8) CHECK (factor_actualizacion >= 0),
  origen             TEXT NOT NULL REFERENCES origen,
  id_certificado     UUID REFERENCES certificado,
  fecha_creacion     TIMESTAMPTZ NOT NULL DEFAULT now(),
  fecha_modificacion TIMESTAMPTZ NOT NULL DEFAULT now(),
  forma_modificacion TEXT NOT NULL DEFAULT 'Ingreso manual',
  CONSTRAINT bolsa_solo_origen_sistema CHECK ((id_corredor IS NULL) = (origen = 'Sistema/Bolsa'))
);
-- Llave de negocio: una calificación por corredor (o Bolsa) / ejercicio / mercado / instrumento / secuencia
CREATE UNIQUE INDEX ux_calificacion_llave ON calificacion_tributaria
  (COALESCE(id_corredor, 0), anio_tributario, mercado, id_instrumento, secuencia_evento);
CREATE INDEX ix_cal_corredor_filtros ON calificacion_tributaria (id_corredor, anio_tributario, mercado);
CREATE INDEX ix_cal_instrumento      ON calificacion_tributaria (id_instrumento);
CREATE INDEX ix_cal_origen           ON calificacion_tributaria (origen);
CREATE INDEX ix_cal_certificado      ON calificacion_tributaria (id_certificado) WHERE id_certificado IS NOT NULL;

-- Valores por columna del certificado (factores 8 a 37): una fila por factor, sin grupos repetidos
CREATE TABLE calificacion_valor (
  id_calificacion INT      NOT NULL REFERENCES calificacion_tributaria ON DELETE CASCADE,
  nro_factor      SMALLINT NOT NULL REFERENCES factor_catalogo,
  monto           NUMERIC(18,2) CHECK (monto >= 0),      -- NULL si la calificación se ingresó directamente por factor
  factor          NUMERIC(10,8) NOT NULL CHECK (factor >= 0 AND factor <= 1),
  PRIMARY KEY (id_calificacion, nro_factor)
);

-- Regla de negocio en la base: la suma de los factores 8 al 19 no puede superar 1
-- (tolerancia de 0,00000006 = 12 columnas x medio punto del 8.º decimal, por redondeo)
CREATE FUNCTION validar_suma_factores() RETURNS trigger AS $$
DECLARE suma NUMERIC;
BEGIN
  SELECT COALESCE(SUM(factor), 0) INTO suma FROM calificacion_valor
   WHERE id_calificacion = NEW.id_calificacion AND nro_factor BETWEEN 8 AND 19;
  IF suma > 1.00000006 THEN
    RAISE EXCEPTION 'La suma de los factores 8 al 19 es % y supera 1', suma USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_suma_factores AFTER INSERT OR UPDATE ON calificacion_valor
  FOR EACH ROW EXECUTE FUNCTION validar_suma_factores();

-- ---------- Auditoría (solo inserción) ----------
CREATE TABLE log_auditoria (
  id_log     BIGSERIAL PRIMARY KEY,
  id_usuario INT REFERENCES usuario,
  accion     TEXT NOT NULL,
  entidad    TEXT,
  detalle    JSONB,
  ts         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_log_ts ON log_auditoria (ts DESC);
CREATE INDEX ix_log_usuario ON log_auditoria (id_usuario, ts DESC);
CREATE FUNCTION bloquear_cambios_log() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'log_auditoria es de solo inserción'; END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_log_inmutable BEFORE UPDATE OR DELETE ON log_auditoria
  FOR EACH ROW EXECUTE FUNCTION bloquear_cambios_log();

-- ---------- Datos de catálogo ----------
INSERT INTO rol VALUES (1, 'Corredor'), (2, 'Administrador'), (3, 'Auditor');
INSERT INTO mercado VALUES ('ACN', 'Acciones'), ('CFI', 'Cuotas de fondos de inversión'), ('FMU', 'Fondos mutuos');
INSERT INTO origen VALUES ('Manual', 'Corredor'), ('Carga masiva montos', 'Corredor'),
                          ('Carga masiva factores', 'Corredor'), ('Certificado', 'Corredor'),
                          ('Sistema/Bolsa', 'Entidad prestadora');
INSERT INTO factor_catalogo
  SELECT n, 'Factor ' || n, 'Columna ' || n || ' del certificado del SII (Cert. 70 / DJ 1948, Cert. 44 / DJ 1922)'
  FROM generate_series(8, 37) AS n;
-- Homologación inicial: columna n del formato de origen -> factor n (reemplazar por el mapeo oficial de Nuam si difiere)
INSERT INTO homologacion_columna SELECT t, n, n FROM unnest(ARRAY['70', '44']) AS t, generate_series(8, 37) AS n;
