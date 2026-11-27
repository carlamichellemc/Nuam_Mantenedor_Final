"use strict";
const $ = (id) => document.getElementById(id);
const E = (t, props = {}, ...hijos) => { const e = document.createElement(t); for (const [k, v] of Object.entries(props)) { if (k.includes("-")) e.setAttribute(k, v); else e[k] = v; } hijos.flat().forEach(h => e.append(h)); return e; };
const S = { token: null, rol: null, nombre: null, cat: null, pagina: 1, tam: 25, total: 0, editando: null, desdeBolsa: false, idCert: null, instrumentos: [] };
const NROS = Array.from({ length: 30 }, (_, i) => i + 8);

async function api(ruta, opc = {}) {
  const h = { ...(opc.headers || {}) };
  if (S.token) h.Authorization = "Bearer " + S.token;
  let cuerpo = opc.body;
  if (opc.json !== undefined) { h["Content-Type"] = "application/json"; cuerpo = JSON.stringify(opc.json); }
  const r = await fetch(ruta, { method: opc.method || "GET", headers: h, body: cuerpo });
  if (r.status === 401 && S.token) { cerrarSesion(); throw new Error("Sesión expirada. Ingrese nuevamente."); }
  const ct = r.headers.get("content-type") || "";
  const datos = ct.includes("json") ? await r.json() : await r.blob();
  if (!r.ok && !opc.tolerar) { const e = new Error((datos && datos.error) || "Error"); e.datos = datos; e.status = r.status; throw e; }
  return opc.tolerar ? { ok: r.ok, status: r.status, datos } : datos;
}
function aviso(msg, mal = false) {
  const a = $("aviso"); a.textContent = msg; a.className = "aviso" + (mal ? " mal" : "");
  clearTimeout(aviso.t); aviso.t = setTimeout(() => a.classList.add("oculto"), 6000);
}
const fmt = (v, d = 8) => (v === null || v === undefined ? "" : Number(v).toFixed(d));
const fecha = (s) => (s ? s.slice(0, 10).split("-").reverse().join("-") : "");
const ts = (s) => (s ? s.replace("T", " ").slice(0, 19) : "");

// ---------------------------------------------------------------- sesión
$("form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault(); $("l-error").textContent = "";
  try {
    const d = await api("/login", { method: "POST", json: { email: $("l-email").value, password: $("l-pass").value } });
    Object.assign(S, { token: d.token, rol: d.rol, nombre: d.nombre });
    $("l-pass").value = "";
    await iniciar();
  } catch (e) { $("l-error").textContent = e.message; }
});
function cerrarSesion() { S.token = null; $("app").classList.add("oculto"); $("login").classList.remove("oculto"); }
$("salir").onclick = cerrarSesion;

const VISTAS = [
  ["v-cal", "Calificaciones", ["Corredor", "Administrador", "Auditor"]],
  ["v-csv", "Carga masiva", ["Corredor"]],
  ["v-cert", "Certificados", ["Corredor"]],
  ["v-usr", "Usuarios", ["Administrador"]],
  ["v-log", "Auditoría", ["Administrador", "Auditor"]],
];
function mostrar(id) {
  VISTAS.forEach(([v]) => $(v).classList.toggle("oculto", v !== id));
  [...$("menu").children].forEach(b => b.classList.toggle("activa", b.dataset.v === id));
  if (id === "v-cal") buscar(); if (id === "v-usr") cargarUsuarios(); if (id === "v-log") cargarLog();
}
async function iniciar() {
  $("login").classList.add("oculto"); $("app").classList.remove("oculto");
  $("u-nombre").textContent = S.nombre; $("u-rol").textContent = S.rol;
  $("menu").replaceChildren(...VISTAS.filter(v => v[2].includes(S.rol)).map(([id, t]) => E("button", { textContent: t, onclick: () => mostrar(id), "data-v": id })));
  $("b-nueva").classList.toggle("oculto", S.rol !== "Corredor");
  S.cat = await api("/catalogos");
  const llenar = (sel, items, vacio) => sel.replaceChildren(...(vacio ? [E("option", { value: "", textContent: vacio })] : []), ...items);
  llenar($("f-mercado"), S.cat.mercados.map(m => E("option", { value: m.codigo, textContent: `${m.codigo} · ${m.nombre}` })), "Todos");
  llenar($("f-origen"), S.cat.origenes.map(o => E("option", { value: o.codigo, textContent: o.codigo })), "Todos");
  llenar($("k-mercado"), S.cat.mercados.map(m => E("option", { value: m.codigo, textContent: `${m.codigo} · ${m.nombre}` })));
  llenar($("i-mercado"), S.cat.mercados.map(m => E("option", { value: m.codigo, textContent: m.codigo })));
  llenar($("du-corr"), [E("option", { value: "", textContent: "—" }), ...S.cat.corredores.map(c => E("option", { value: c.id_corredor, textContent: `${c.nombre} (${c.pais})` }))]);
  mostrar("v-cal");
}

// ---------------------------------------------------------------- listado
function filtros() {
  const p = new URLSearchParams({ pagina: S.pagina, tam: S.tam });
  [["mercado", "f-mercado"], ["origen", "f-origen"], ["fuente", "f-fuente"], ["anio", "f-anio"], ["instrumento", "f-instr"]].forEach(([k, id]) => { if ($(id).value.trim()) p.set(k, $(id).value.trim()); });
  return p;
}
async function buscar() {
  try {
    const d = await api("/calificaciones?" + filtros());
    S.total = d.total;
    const cab = ["Ejercicio", "Mercado", "Instrumento", "Sec.", "Div.", "Soc.", "Fecha pago", "Valor hist.", "Origen", "Fuente", ...NROS.map(n => "F" + n), ""];
    const th = E("tr", {}, cab.map((c, i) => E("th", { textContent: c, className: i >= 10 ? "num" : "", title: i >= 10 && c ? (S.cat.factores.find(f => "F" + f.nro_factor === c) || {}).nombre : "" })));
    const filas = d.filas.map(f => {
      const bolsa = f.origen === "Sistema/Bolsa";
      const tr = E("tr", {},
        E("td", { textContent: f.ejercicio }), E("td", { textContent: f.mercado }), E("td", { textContent: f.instrumento }),
        E("td", { textContent: f.secuencia }), E("td", { textContent: f.numero_dividendo ?? "" }), E("td", { textContent: f.tipo_sociedad || "" }),
        E("td", { textContent: fecha(f.fecha_pago) }), E("td", { className: "num", textContent: f.valor_historico ? fmt(f.valor_historico, 2) : "" }),
        E("td", {}, E("span", { className: "chip" + (bolsa ? " bolsa" : ""), textContent: f.origen })), E("td", { textContent: f.fuente }),
        ...NROS.map(n => E("td", { className: "num", textContent: f.factores && f.factores[n] !== undefined ? fmt(f.factores[n]) : "" })),
        E("td", {}, E("button", { className: "enlace", textContent: S.rol === "Corredor" ? "Modificar" : "Ver", onclick: () => abrirCal(f.id_calificacion) }),
          ...(S.rol === "Corredor" && !bolsa ? [E("button", { className: "enlace", textContent: "Eliminar", onclick: () => eliminar(f) })] : [])));
      return tr;
    });
    $("t-cal").replaceChildren(E("thead", {}, th), E("tbody", {}, filas.length ? filas : [E("tr", {}, E("td", { colSpan: 41, textContent: "Sin resultados" }))]));
    const pags = Math.max(1, Math.ceil(d.total / d.tam));
    $("p-info").textContent = `Página ${d.pagina} de ${pags} · ${d.total} calificaciones`;
    $("p-ant").disabled = d.pagina <= 1; $("p-sig").disabled = d.pagina >= pags;
  } catch (e) { aviso(e.message, true); }
}
$("filtros").addEventListener("submit", (e) => { e.preventDefault(); S.pagina = 1; buscar(); });
$("f-limpiar").onclick = () => setTimeout(() => { S.pagina = 1; buscar(); });
$("p-ant").onclick = () => { S.pagina--; buscar(); };
$("p-sig").onclick = () => { S.pagina++; buscar(); };
async function eliminar(f) {
  if (!confirm(`¿Eliminar la calificación ${f.instrumento} / ${f.ejercicio} / sec. ${f.secuencia}? Quedará registrado en la auditoría.`)) return;
  try { await api("/calificaciones/" + f.id_calificacion, { method: "DELETE" }); aviso("Calificación eliminada"); buscar(); } catch (e) { aviso(e.message, true); }
}

// ---------------------------------------------------------------- formulario
function modo() { return document.querySelector("input[name=modo]:checked").value; }
function dibujarGrilla(montos = {}, factores = {}) {
  const m = modo();
  $("k-grilla").replaceChildren(...NROS.map(n => {
    const nombre = (S.cat.factores.find(f => f.nro_factor === n) || {}).nombre || "Factor " + n;
    const v = m === "montos" ? montos[n] : factores[n];
    return E("div", { className: "celda" + (n < 20 ? " g1" : "") },
      E("small", { textContent: `F${n} · ${nombre}`, title: n < 20 ? "Columnas 8 a 19: su suma no puede superar 1" : "" }),
      E("input", { id: "v" + n, inputMode: "decimal", value: v !== undefined && v !== null ? (m === "montos" ? String(Number(v)) : fmt(v)) : "", "aria-label": nombre }),
      E("span", { className: "calc", id: "c" + n, textContent: m === "montos" && factores[n] !== undefined ? "→ " + fmt(factores[n]) : "" }));
  }));
}
function valores() { const o = {}; NROS.forEach(n => { const v = $("v" + n).value.trim(); if (v !== "") o[n] = v; }); return o; }
document.querySelectorAll("input[name=modo]").forEach(r => r.addEventListener("change", () => dibujarGrilla()));
async function cargarInstrumentos(sel) {
  S.instrumentos = await api("/instrumentos");
  $("k-instr").replaceChildren(...S.instrumentos.map(i => E("option", { value: i.id_instrumento, textContent: `${i.codigo}${i.inscrito ? "" : " (no inscrito)"}` })));
  if (sel) $("k-instr").value = sel;
}
function limpiarForm() {
  $("form-cal").reset(); $("k-error").textContent = ""; $("k-suma").textContent = ""; S.idCert = null;
  $("k-ejercicio").value = new Date().getFullYear();
}
function bloquear(solo) {
  document.querySelectorAll("#form-cal input, #form-cal select").forEach(e => e.disabled = solo);
  $("k-grabar").classList.toggle("oculto", solo); $("k-calcular").classList.toggle("oculto", solo); $("k-nuevo-instr").classList.toggle("oculto", solo);
}
async function abrirCal(id, previa) {
  limpiarForm(); await cargarInstrumentos();
  S.editando = id || null; S.desdeBolsa = false;
  $("d-titulo").textContent = id ? (S.rol === "Corredor" ? "Modificar calificación" : "Detalle de calificación") : "Ingresar calificación";
  let montos = {}, factores = {};
  if (id) {
    const d = await api("/calificaciones/" + id);
    S.desdeBolsa = d.origen === "Sistema/Bolsa";
    $("k-ejercicio").value = d.ejercicio; $("k-mercado").value = d.mercado; $("k-instr").value = d.id_instrumento; $("k-sec").value = d.secuencia;
    $("k-div").value = d.numero_dividendo ?? 0; $("k-tipo").value = d.tipo_sociedad || ""; $("k-fecha").value = d.fecha_pago ? d.fecha_pago.slice(0, 10) : "";
    $("k-valor").value = d.valor_historico ?? ""; $("k-desc").value = d.descripcion || ""; $("k-fact-act").value = d.factor_actualizacion ?? ""; $("k-isfut").checked = !!d.isfut;
    montos = d.montos || {}; factores = d.factores || {};
    if (!d.montos) document.querySelector("input[name=modo][value=factores]").checked = true;
  } else if (previa) {
    montos = previa.montos; S.idCert = previa.id_certificado;
    const b = previa.datos_base;
    $("k-ejercicio").value = b.ejercicio || ""; if (b.mercado) $("k-mercado").value = b.mercado; $("k-sec").value = b.secuencia ?? ""; $("k-div").value = b.numero_dividendo ?? 0;
    $("k-tipo").value = b.tipo_sociedad || ""; $("k-valor").value = b.valor_historico ?? ""; if (b.fecha_pago) $("k-fecha").value = b.fecha_pago.length === 10 && b.fecha_pago[4] === "-" ? b.fecha_pago : "";
    if (previa.instrumento) $("k-instr").value = previa.instrumento.id_instrumento;
  }
  $("d-bolsa").classList.toggle("oculto", !S.desdeBolsa || S.rol !== "Corredor");
  dibujarGrilla(montos, factores); bloquear(S.rol !== "Corredor");
  if (id && Object.keys(montos).length) calcular(true);
  $("d-cal").showModal();
}
function cuerpo() {
  return { ejercicio: $("k-ejercicio").value, mercado: $("k-mercado").value, id_instrumento: $("k-instr").value, secuencia: $("k-sec").value,
    numero_dividendo: $("k-div").value || 0, tipo_sociedad: $("k-tipo").value || null, fecha_pago: $("k-fecha").value || null, valor_historico: $("k-valor").value || null,
    descripcion: $("k-desc").value || null, factor_actualizacion: $("k-fact-act").value || null, isfut: $("k-isfut").checked, modo: modo(), valores: valores(),
    ...(S.idCert ? { id_certificado: S.idCert } : {}) };
}
async function calcular(silencioso) {
  $("k-error").textContent = "";
  try {
    const d = await api("/calificaciones/calcular", { method: "POST", json: { modo: modo(), valores: valores() } });
    NROS.forEach(n => { const c = $("c" + n); if (c) c.textContent = d.factores[n] !== undefined ? "→ " + fmt(d.factores[n]) : ""; });
    $("k-suma").textContent = `Suma de factores 8 a 19: ${d.suma_8_19} (máximo 1)`;
    return true;
  } catch (e) { if (!silencioso) $("k-error").textContent = e.message; return false; }
}
$("k-calcular").onclick = () => calcular(false);
$("k-grabar").onclick = async () => {
  $("k-error").textContent = "";
  if (!$("form-cal").reportValidity()) return;
  try {
    const r = S.editando ? await api("/calificaciones/" + S.editando, { method: "PUT", json: cuerpo() }) : await api("/calificaciones", { method: "POST", json: cuerpo() });
    $("d-cal").close();
    aviso(r.copia_local ? "Se creó la versión de su corredora; la calificación de la Bolsa no fue modificada." : "Calificación grabada correctamente");
    buscar();
  } catch (e) { $("k-error").textContent = e.message; }
};
$("k-cancelar").onclick = () => $("d-cal").close();
$("b-nueva").onclick = () => abrirCal(null);

// instrumento no inscrito
$("k-nuevo-instr").onclick = () => { $("i-error").textContent = ""; $("i-codigo").value = ""; $("i-emisor").value = ""; $("i-mercado").value = $("k-mercado").value; $("d-instr").showModal(); };
$("i-cancelar").onclick = () => $("d-instr").close();
$("i-grabar").onclick = async () => {
  try {
    const d = await api("/instrumentos", { method: "POST", json: { codigo: $("i-codigo").value, nombre_emisor: $("i-emisor").value, mercado: $("i-mercado").value } });
    await cargarInstrumentos(d.id_instrumento); $("d-instr").close();
  } catch (e) { $("i-error").textContent = e.message; }
};

// ---------------------------------------------------------------- carga masiva
function descargar(blob, nombre) { const a = E("a", { href: URL.createObjectURL(blob), download: nombre }); document.body.append(a); a.click(); a.remove(); }
$("c-plantilla").onclick = async () => { try { descargar(await api("/plantilla?tipo=" + $("c-tipo").value), `plantilla_${$("c-tipo").value}.csv`); } catch (e) { aviso(e.message, true); } };
async function enviarCsv(modoEnvio) {
  const f = $("c-archivo").files[0];
  if (!f) { aviso("Seleccione un archivo CSV", true); return null; }
  const fd = new FormData(); fd.append("archivo", f);
  return api(`/calificaciones/csv?tipo=${$("c-tipo").value}&modo=${modoEnvio}`, { method: "POST", body: fd, tolerar: true });
}
function pintarResumen(r) {
  const res = r.datos.resumen;
  const caja = (t, v) => E("div", {}, E("b", { textContent: v }), t);
  const cont = [E("div", { className: "resumen" }, caja("filas", res.total), caja("nuevas", res.nuevas), caja("se actualizan", res.actualizan), caja("con errores", res.con_errores))];
  if (r.datos.error) cont.push(E("p", { className: "error", textContent: r.datos.error }));
  const filas = (r.datos.filas || []).map(f => E("tr", {}, E("td", { textContent: f.linea }), E("td", { className: "estado-" + f.estado, textContent: { nueva: "Nueva", actualiza: "Actualiza", error: "Error" }[f.estado] }),
    E("td", { textContent: f.instrumento ? `${f.instrumento} · ${f.ejercicio} · ${f.mercado} · sec. ${f.secuencia}` : "" }), E("td", { textContent: f.errores.join(" · ") || (f.factores ? "F8 = " + fmt(f.factores[8] ?? 0) : "") })));
  cont.push(E("div", { className: "tabla-wrap" }, E("table", {}, E("thead", {}, E("tr", {}, ["Línea", "Estado", "Calificación", "Detalle"].map(t => E("th", { textContent: t })))), E("tbody", {}, filas))));
  if (r.ok && res.con_errores === 0 && res.total) cont.push(E("div", { className: "botones" }, E("button", { className: "primario", textContent: `Confirmar y guardar ${res.total} filas`, onclick: confirmarCsv })));
  $("c-res").replaceChildren(...cont); $("c-res").classList.remove("oculto");
}
$("c-prev").onclick = async () => { try { const r = await enviarCsv("previsualizar"); if (r) pintarResumen(r); } catch (e) { aviso(e.message, true); } };
async function confirmarCsv() {
  const r = await enviarCsv("confirmar");
  if (r.ok) { $("c-res").classList.add("oculto"); aviso(`Carga confirmada (lote ${r.datos.lote}): ${r.datos.resumen.nuevas} nuevas, ${r.datos.resumen.actualizan} actualizadas`); $("c-archivo").value = ""; }
  else pintarResumen(r);
}

// ---------------------------------------------------------------- certificados
$("k-subir").onclick = async () => {
  const f = $("k-archivo").files[0];
  if (!f) { aviso("Seleccione un PDF", true); return; }
  $("k-estado").textContent = "Procesando… (si el PDF es escaneado se usa OCR y puede tardar unos segundos)";
  const fd = new FormData(); fd.append("archivo", f);
  try {
    const d = await api("/certificados", { method: "POST", body: fd });
    $("k-estado").textContent = `Certificado ${d.tipo} leído${d.ocr_usado ? " con OCR" : ""}.` + (d.columnas_sin_mapeo && d.columnas_sin_mapeo.length ? ` Columnas sin homologar: ${d.columnas_sin_mapeo.join(", ")}.` : "");
    await abrirCal(null, d);
  } catch (e) { $("k-estado").textContent = ""; aviso(e.message, true); }
};

// ---------------------------------------------------------------- usuarios y log
async function cargarUsuarios() {
  const u = await api("/usuarios");
  $("t-usr").replaceChildren(E("thead", {}, E("tr", {}, ["Nombre", "Correo", "Rol", "Corredora", "Estado", ""].map(t => E("th", { textContent: t })))),
    E("tbody", {}, u.map(x => E("tr", {}, E("td", { textContent: x.nombre }), E("td", { textContent: x.email }), E("td", { textContent: x.rol }), E("td", { textContent: x.id_corredor ?? "—" }),
      E("td", { textContent: x.activo ? "Activo" : "Inactivo" }),
      E("td", {}, E("button", { className: "enlace", textContent: x.activo ? "Desactivar" : "Activar", onclick: async () => { try { await api("/usuarios/" + x.id_usuario, { method: "PUT", json: { activo: !x.activo } }); cargarUsuarios(); } catch (e) { aviso(e.message, true); } } }))))));
}
$("u-nuevo").onclick = () => { ["du-nombre", "du-email", "du-pass"].forEach(i => $(i).value = ""); $("du-error").textContent = ""; $("d-usr").showModal(); };
$("du-cancelar").onclick = () => $("d-usr").close();
$("du-grabar").onclick = async () => {
  try {
    await api("/usuarios", { method: "POST", json: { nombre: $("du-nombre").value, email: $("du-email").value, password: $("du-pass").value, rol: $("du-rol").value, id_corredor: $("du-corr").value ? Number($("du-corr").value) : null } });
    $("d-usr").close(); aviso("Usuario creado"); cargarUsuarios();
  } catch (e) { $("du-error").textContent = e.message; }
};
async function cargarLog() {
  const q = $("l-accion").value.trim();
  const l = await api("/log" + (q ? "?accion=" + encodeURIComponent(q) : ""));
  $("t-log").replaceChildren(E("thead", {}, E("tr", {}, ["Fecha", "Usuario", "Acción", "Entidad", ""].map(t => E("th", { textContent: t })))),
    E("tbody", {}, l.map(x => E("tr", {}, E("td", { textContent: ts(x.ts) }), E("td", { textContent: x.usuario || "—" }), E("td", { textContent: x.accion }), E("td", { textContent: x.entidad || "" }),
      E("td", {}, E("button", { className: "enlace", textContent: "Ver antes/después", onclick: () => { $("det-cuerpo").replaceChildren(E("h3", { textContent: `${x.accion} · ${ts(x.ts)}` }), E("pre", { textContent: JSON.stringify(x.detalle, null, 2) })); $("d-det").showModal(); } }))))));
}
$("l-filtro").addEventListener("submit", (e) => { e.preventDefault(); cargarLog(); });
$("det-cerrar").onclick = () => $("d-det").close();
