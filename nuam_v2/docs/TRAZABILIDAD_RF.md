# Matriz de trazabilidad requisito → prueba

Ejecución: `pytest tests -q` → **88 pruebas pasan** (algunas parametrizadas).

| Requisito | Descripción | Pruebas |
|---|---|---|
| RF1 | Mantenedor con filtros mercado/origen/período | `test_RF1_filtros_mercado_origen_periodo` |
| RF2 | Búsqueda eficiente (paginada, indexada) | `test_RF2_busqueda_paginada` |
| RF3 | CRUD de calificaciones | `test_RF3_modificar_y_eliminar_con_log_antes_despues`, `test_RF3_llave_duplicada_devuelve_409` |
| RF4 | Ingreso manual con todos los datos base | `test_RF4_ingreso_con_todos_los_datos_base` |
| RF5 | Ingreso de montos (Calcular/Grabar/Cancelar) | `test_RF5_RF6_calcular_y_grabar_por_montos` |
| RF6 | Cálculo automático factores 8–37 y validación suma 8–19 ≤ 1 | `test_RF5_RF6_calcular_y_grabar_por_montos`, `test_RF6_30_factores_del_8_al_37`, `test_RF6_suma_mayor_a_1_se_bloquea` |
| RF7 | Ingreso/edición directa de factores | `test_RF7_ingreso_directo_por_factores`, `test_U12_ingreso_directo_de_factores_RF7` |
| RF8 | Instrumentos no inscritos | `test_RF8_instrumento_no_inscrito_es_local_del_corredor` |
| RF9 | Carga masiva CSV con previsualización y validación | `test_RF9_previsualizar_no_guarda_nada`, `test_RF9_validacion_de_formato_por_fila`, `test_RF9_carga_por_montos_y_por_factores`, `test_RF9_formatos_coma_y_punto_y_coma_y_plantilla`, `test_RF9_archivos_invalidos` |
| RF10 | Crear/actualizar por llave en carga masiva | `test_RF10_crear_si_no_existe_actualizar_si_existe` |
| RF11 | Columna origen | `test_RF11_columna_origen_en_todas_las_vias` |
| RF12 | Log de ingreso, modificación y eliminación | `test_RF12_log_de_ingreso_modificacion_eliminacion` |
| RF13 | Homologación de certificados 70/44 y DJ 1948/1922 (IDP/OCR) | `test_RF13_certificado_70_con_texto`, `test_RF13_certificado_44_y_dj`, `test_RF13_homologacion_de_columnas_configurable`, `test_RF13_certificado_escaneado_usa_ocr`, `test_RF13_certificado_invalido`, `test_RF13_certificado_original_se_puede_volver_a_descargar` |

## Reglas de negocio (Bolsa vs. corredor)
`test_REGLA_el_corredor_ve_la_info_de_la_bolsa`, `test_REGLA_editar_calificacion_de_bolsa_crea_version_local_y_prima`, `test_REGLA_la_bolsa_no_se_puede_eliminar`, `test_REGLA_lo_ingresado_es_local_para_cada_corredor`, `test_REGLA_ningun_ingreso_masivo_altera_la_bolsa`, `test_REGLA_auditor_y_administrador_ven_todo_en_solo_lectura`

## No funcionales
| Requisito | Pruebas |
|---|---|
| RNF1 Seguridad | `test_S01_inyeccion_sql_neutralizada`, `test_S02_autenticacion_y_roles`, `test_S03_token_expirado_o_manipulado`, `test_S04_bloqueo_por_intentos_y_cabeceras`, `test_S05_aislamiento_entre_corredores`, `test_S06_errores_genericos_sin_detalles_tecnicos`, `test_S07_entradas_hostiles_no_rompen_el_sistema`, `test_S08_archivos_peligrosos`, `test_S09_contrasenas_con_hash` |
| RNF2 Integridad y trazabilidad | `test_BD01_trigger_suma_8_a_19`, `test_BD02_factor_fuera_de_rango_y_numero_de_factor`, `test_BD03_log_inmutable`, `test_BD04_llave_unica_y_reglas_de_origen`, `test_BD05_borrar_calificacion_borra_sus_valores`, `test_BD06_los_indices_existen`, `test_BD07_la_consulta_principal_usa_indice` · `test_ST01_storage_local`, `test_ST02_claves_invalidas`, `test_ST03_storage_s3_en_la_nube_simulada` |
| RNF3 Eficiencia | `perf_test.py` (500 filas en <1 s; 50 usuarios, máx 0,71 s) |
| RNF4 Usabilidad | Manual de usuario, validaciones con mensajes claros; prueba con usuarios pendiente |
| RNF5 Disponibilidad | Estrés: 200 usuarios concurrentes sin errores (`resultados_rendimiento.txt`) |
| RNF6 Escalabilidad | Storage S3 intercambiable (ST03), pool de conexiones, Gunicorn multiproceso |

## Unitarias del motor de cálculo
`test_U01_factor_8_con_8_decimales_exactos`, `test_U02_redondeo_al_octavo_decimal`, `test_U03_suma_8_a_19_mayor_que_1_se_rechaza`, `test_U04_suma_exactamente_1_se_acepta`, `test_U05_tolerancia_de_redondeo`, `test_U06_factores_20_a_37_no_cuentan_en_la_suma_8_19`, `test_U07_30_factores_8_al_37`, `test_U08_factor_mayor_que_1_se_rechaza`, `test_U09_suma_cero_y_montos_negativos`, `test_U10_monto_cero_en_una_columna`, `test_U11_numero_de_factor_inexistente`, `test_U13_formatos_de_numero`, `test_U14_numeros_invalidos`, `test_U15_datos_base_validos_y_normalizados`, `test_U16_datos_base_invalidos`
