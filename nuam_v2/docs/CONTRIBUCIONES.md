# Contribuciones del equipo

**Proyecto:** Mantenedor CORE Web de Calificaciones Tributarias · Caso Nuam Exchange · INACAP
**Integrantes:** Carla Caro y Manuel Montecinos

## 1. Distribución del trabajo
| Integrante | Rol | Participación |
|---|---|---|
| Carla Caro | Líder técnica y desarrolladora principal | Mayor parte del proyecto: análisis, diseño, desarrollo, pruebas y documentación |
| Manuel Montecinos | Apoyo en desarrollo y documentación | Colaboración en tareas puntuales de análisis, revisión y documentación (detalle en la sección 3) |

## 2. Contribuciones de Carla Caro
| Área | Aporte |
|---|---|
| Análisis del caso | Análisis de la organización y la problemática de Nuam; levantamiento de requisitos funcionales (RF1–RF13) y no funcionales (RNF1–RNF6); historias de usuario |
| Diseño de la solución | Documento de diseño de la solución informática; arquitectura 4+1; modelo de datos y elección de PostgreSQL con Object Storage |
| Base de datos | `schema.sql` (3FN, índices, restricciones y triggers), `seed.py`, diccionario de datos |
| Backend | API en Flask: autenticación JWT, control por rol, cálculo de factores 8–37, reglas entre la Bolsa y las corredoras, carga masiva CSV, homologación de certificados con OCR, log de auditoría |
| Frontend | Interfaz web completa: listado con filtros, formulario de ingreso y modificación, carga masiva con previsualización, certificados, usuarios y auditoría |
| Pruebas | Plan de pruebas, 88 pruebas automatizadas, pruebas de rendimiento y estrés, matriz de trazabilidad |
| Documentación | README con instalación paso a paso, manual de usuario, informe de pruebas, instalador y archivos de despliegue |
| Presentación | Contenido de la presentación y preparación de la demostración |

## 3. Contribuciones de Manuel Montecinos
| Área | Aporte |
|---|---|
| Análisis y requisitos | Participación en el análisis del caso y revisión de los requisitos |
| Revisión | Revisión de documentos y de la interfaz, con observaciones para corregir |
| Documentación y presentación | Apoyo en la elaboración de los documentos de la entrega y de la presentación |

## 4. Metodología de trabajo
- Reparto del trabajo por áreas (análisis, base de datos, backend, frontend, pruebas y documentación), con Carla a cargo de la parte técnica.
- Revisión del avance entre ambos antes de cada entrega y corrección de las observaciones.
- Las pruebas automatizadas se ejecutaron después de cada cambio importante para detectar fallas a tiempo.

## 5. Decisiones relevantes
| Decisión | Motivo |
|---|---|
| PostgreSQL para los datos estructurados y Object Storage para los PDF originales | Integridad relacional para las calificaciones y almacenamiento adecuado para documentos |
| Los 30 factores (8 al 37) en una tabla hija, no en 30 columnas | Normalización y facilidad para cambiar nombres o cantidad de factores |
| La versión del corredor prevalece sobre la de la Bolsa, sin modificar la de la Bolsa | Regla de negocio del caso: la información de la Bolsa es la fuente oficial y no se altera |
| Mapeo de homologación configurable en la base de datos | El mapeo oficial de Nuam puede cargarse sin cambiar el código |
| Log de auditoría inmutable por trigger | Trazabilidad exigida para información tributaria |
