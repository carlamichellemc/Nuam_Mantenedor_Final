# Manual de usuario · Mantenedor CORE de Calificaciones Tributarias

## 1. Ingreso y roles
Ingrese con su correo y contraseña. Tras 5 intentos fallidos se bloquea 5 minutos. La sesión dura 15 minutos.
| Rol | Puede |
|---|---|
| Corredor | Ver, ingresar, modificar y eliminar sus calificaciones; carga masiva; homologar certificados; ver la información de la Bolsa |
| Administrador | Ver todo (solo lectura); administrar usuarios; ver el log |
| Auditor | Ver todo (solo lectura) y el log de auditoría |

## 2. Consultar calificaciones (HU: búsqueda)
Pestaña **Calificaciones**. Filtre por Mercado (ACN, CFI, FMU), Origen, Fuente (Corredor / Entidad prestadora), Ejercicio e Instrumento y pulse **Buscar**; **Limpiar** quita los filtros.
La grilla muestra los datos base y los factores 8 al 37 (desplácese a la derecha). La insignia amarilla *Sistema/Bolsa* indica información de la Bolsa.

## 3. Ingresar una calificación
1. **+ Ingresar calificación**. Complete ejercicio, mercado, instrumento y secuencia (obligatorios) y los demás datos base.
2. Si el instrumento no existe, use **¿Instrumento no inscrito? Crear**: queda disponible solo para su corredora.
3. Elija la forma de ingreso: **Por montos** (el sistema calcula cada factor = monto / suma de montos de las columnas 8–19) o **Por factores** (ingreso directo).
4. **Calcular** muestra los factores con 8 decimales y la suma 8–19, que no puede superar 1.
5. **Grabar** guarda; **Cancelar** descarta. Si hay un error (suma > 1, factor fuera de 0–1, llave repetida) se muestra el motivo y no se guarda nada.

## 4. Modificar y eliminar
**Modificar** abre el mismo formulario con los datos actuales. Si la calificación proviene de la Bolsa, se avisa y, al grabar, se crea una versión propia de su corredora (la de la Bolsa no cambia y su versión prevalece para usted). La información de la Bolsa no puede eliminarse. **Eliminar** pide confirmación y queda en el log.

## 5. Carga masiva (CSV)
1. Pestaña **Carga masiva**, elija *Por montos* o *Por factores* y **Descargar plantilla**.
2. Columnas: Ejercicio, Mercado, Instrumento, Fecha (DD-MM-AAAA), Secuencia, Numero_dividendo, Tipo_sociedad (A/C), Valor_historico y Monto_8…Monto_37 (o Factor_8…Factor_37). Separador `;` o `,`.
3. **Previsualizar**: muestra cuántas filas son nuevas, cuántas actualizan una existente y los errores por línea. No guarda nada.
4. Si no hay errores aparece **Confirmar y guardar**. La carga es todo o nada.

## 6. Homologar un certificado
Pestaña **Certificados** → elija el PDF (Certificado 70/44 o DJ 1948/1922, con texto o escaneado) → **Extraer datos**. El sistema lee el documento (OCR si es imagen), homologa las columnas a los factores y abre el formulario precargado: revise, corrija y **Grabar**. El PDF original queda guardado y vinculado (origen *Certificado*).

## 7. Usuarios (Administrador)
Pestaña **Usuarios**: **+ Nuevo usuario** (contraseña mínimo 8 caracteres; un Corredor debe tener corredora) y **Activar/Desactivar**.

## 8. Auditoría
Pestaña **Auditoría**: filtre por acción y use **Ver antes/después** para ver el detalle. El registro no se puede editar ni borrar.

## 9. Mensajes frecuentes
| Mensaje | Causa y solución |
|---|---|
| La suma de factores 8 a 19 supera 1 | Revise los montos/factores de las columnas 8–19 |
| Ya existe una calificación con la misma llave | Use **Modificar** sobre la existente |
| Instrumento '…' no existe | Créelo como no inscrito antes de la carga |
| Demasiados intentos | Espere 5 minutos |
| Sesión expirada | Vuelva a ingresar |
