# Diccionario de datos (PostgreSQL 16, esquema `public`)

| Tabla | Propósito | Clave | Reglas relevantes |
|---|---|---|---|
| `rol` | Catálogo de roles (1 Corredor, 2 Administrador, 3 Auditor) | `id_rol` | |
| `corredor` | Corredoras (razón social, país Chile/Perú/Colombia) | `id_corredor` | CHECK país |
| `usuario` | Usuarios y hash de contraseña, `activo` | `id_usuario` | email único; un Corredor exige `id_corredor` |
| `mercado` | ACN (acciones), CFI (cuotas fondos de inversión), FMU (fondos mutuos) | `codigo` | |
| `origen` | Origen del registro y su fuente (Corredor / Entidad prestadora) | `codigo` | |
| `factor_catalogo` | Factores 8 al 37 (nombre y concepto) | `nro_factor` | |
| `instrumento` | Instrumentos; `inscrito` FALSE = creado por una corredora | `id_instrumento` | código único (sin distinguir mayúsculas) por creador |
| `certificado` | PDF original (referencia al Object Storage), JSON de extracción, SHA-256, `ocr_usado` | `id_certificado` UUID | tipo 70 o 44 |
| `homologacion_columna` | Mapeo columna del certificado → factor interno | (`tipo_certificado`, `columna_origen`) | configurable |
| `calificacion_tributaria` | Cabecera: ejercicio, mercado, instrumento, secuencia, dividendo, sociedad, fecha, valor histórico, descripción, ISFUT, factor de actualización, origen, fechas | `id_calificacion` | `id_corredor` NULL ⇔ origen *Sistema/Bolsa*; índice único de llave |
| `calificacion_valor` | Un renglón por factor: `monto` (opcional) y `factor` 0..1 | (`id_calificacion`, `nro_factor`) | trigger: suma 8–19 ≤ 1,00000006; ON DELETE CASCADE |
| `log_auditoria` | Bitácora: usuario, acción, entidad, `detalle` JSONB (antes/después), `ts` | `id_log` | trigger impide UPDATE y DELETE |

## Columnas

### calificacion_tributaria
| Columna | Tipo | Nulo |
|---|---|---|
| id_calificacion | integer | No |
| id_corredor | integer | Sí |
| id_instrumento | integer | No |
| anio_tributario | smallint | No |
| mercado | character(3) | No |
| secuencia_evento | integer | No |
| numero_dividendo | integer | Sí |
| tipo_sociedad | character(1) | Sí |
| fecha_pago | date | Sí |
| valor_historico | numeric | Sí |
| descripcion | character varying(200) | Sí |
| isfut | boolean | No |
| factor_actualizacion | numeric | Sí |
| origen | text | No |
| id_certificado | uuid | Sí |
| fecha_creacion | timestamp with time zone | No |
| fecha_modificacion | timestamp with time zone | No |
| forma_modificacion | text | No |

### calificacion_valor
| Columna | Tipo | Nulo |
|---|---|---|
| id_calificacion | integer | No |
| nro_factor | smallint | No |
| monto | numeric | Sí |
| factor | numeric | No |

### certificado
| Columna | Tipo | Nulo |
|---|---|---|
| id_certificado | uuid | No |
| id_corredor | integer | No |
| tipo | text | No |
| archivo | text | No |
| archivo_json | text | No |
| sha256 | text | No |
| ocr_usado | boolean | No |
| extraccion | jsonb | Sí |
| fecha_carga | timestamp with time zone | No |

### corredor
| Columna | Tipo | Nulo |
|---|---|---|
| id_corredor | integer | No |
| razon_social | text | No |
| pais | text | No |

### factor_catalogo
| Columna | Tipo | Nulo |
|---|---|---|
| nro_factor | smallint | No |
| nombre | text | No |
| concepto | text | No |

### homologacion_columna
| Columna | Tipo | Nulo |
|---|---|---|
| tipo_certificado | text | No |
| columna_origen | smallint | No |
| nro_factor | smallint | No |

### instrumento
| Columna | Tipo | Nulo |
|---|---|---|
| id_instrumento | integer | No |
| codigo | text | No |
| nombre_emisor | text | Sí |
| pais_emisor | text | Sí |
| mercado | character(3) | No |
| inscrito | boolean | No |
| id_corredor_creador | integer | Sí |

### log_auditoria
| Columna | Tipo | Nulo |
|---|---|---|
| id_log | bigint | No |
| id_usuario | integer | Sí |
| accion | text | No |
| entidad | text | Sí |
| detalle | jsonb | Sí |
| ts | timestamp with time zone | No |

### mercado
| Columna | Tipo | Nulo |
|---|---|---|
| codigo | character(3) | No |
| nombre | text | No |

### origen
| Columna | Tipo | Nulo |
|---|---|---|
| codigo | text | No |
| fuente | text | No |

### rol
| Columna | Tipo | Nulo |
|---|---|---|
| id_rol | smallint | No |
| nombre_rol | text | No |

### usuario
| Columna | Tipo | Nulo |
|---|---|---|
| id_usuario | integer | No |
| nombre | text | No |
| email | text | No |
| pass_hash | text | No |
| activo | boolean | No |
| id_rol | smallint | No |
| id_corredor | integer | Sí |
| pais | text | Sí |
