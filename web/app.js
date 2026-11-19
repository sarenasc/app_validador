"use strict";

const SECCIONES = [
  { titulo: "Producto", campos: [["especie", "Especie", "lista:especie"], ["variedad", "Variedad", "lista:variedad"],
    ["categoria", "Categoría", "lista:categoria"], ["fecha", "Fecha embalaje", "date"], ["calibre", "Calibre (no se valida)"]] },
  { titulo: "Productor (Grower)", campos: [["csg", "CSG", "lista:csg"], ["prod_region", "Región"], ["prod_provincia", "Provincia"],
    ["prod_comuna", "Comuna"], ["ggn", "GGN"], ["sdp", "SDP (sitio producción)", "lista:sdp"]] },
  { titulo: "Planta (Packed by)", campos: [["csp", "CSP", "lista:csp"], ["planta_region", "Región"], ["planta_provincia", "Provincia"],
    ["planta_comuna", "Comuna"], ["fda", "FDA"], ["coc", "CoC"]] },
  { titulo: "Exportadora", campos: [["cse", "CSE", "lista:cse"], ["exportadora", "Nombre exportadora"]] },
  { titulo: "Embalaje", campos: [["embalaje", "Código embalaje", "lista:embalaje"], ["peso_kg", "Peso neto kg"],
    ["peso_lb", "Peso neto lb"], ["plu", "PLU"]] },
  { titulo: "Proceso", campos: [["proc", "PROC"], ["lote", "Lote"], ["observacion", "Observación", "solo-registro"]] },
];
const CAMPOS = SECCIONES.flatMap((s) => s.campos.map((c) => c[0]));

// Qué campos del formulario se completan desde cada maestro
const AUTOCOMPLETAR = {
  csg: ["productor", "csg", { prod_region: "region", prod_provincia: "provincia", prod_comuna: "comuna", ggn: "ggn" }],
  csp: ["planta", "csp", { planta_region: "region", planta_provincia: "provincia", planta_comuna: "comuna", fda: "fda", coc: "coc" }],
  cse: ["exportadora", "cse", { exportadora: "nombre" }],
  embalaje: ["embalaje", "codigo", { peso_kg: "peso_kg", peso_lb: "peso_lb", plu: "plu", especie: "especie" }],
};

let maestros = {};
let procesos = [];
let editId = null;
let lecturasV = []; // lecturas de las fotos de la etiqueta que se está validando
let ultimoTexto = ""; // texto OCR de la última foto: el servidor busca en él los valores de la base
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(url, opciones = {}) {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opciones,
    body: opciones.body ? JSON.stringify(opciones.body) : undefined });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* */ }
    throw new Error(msg);
  }
  return r.json();
}

function toast(msg, ms = 2500) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.h); toast.h = setTimeout(() => (t.hidden = true), ms);
}

// ---------------- formulario genérico ----------------
function renderForm(prefijo, registro) {
  const f = $(`#${prefijo}-form`);
  f.innerHTML = SECCIONES.map((s) => `
    <fieldset><legend>${s.titulo}</legend><div class="grilla">
      ${s.campos.filter((c) => registro || c[2] !== "solo-registro").map(([k, t, tipo]) => `
        <div class="fld" id="${prefijo}-fld-${k}">
          <label for="${prefijo}-${k}">${t}</label>
          <input id="${prefijo}-${k}" name="${k}" ${tipo === "date" ? 'type="date"' : ""}
            ${tipo && tipo.startsWith("lista:") ? `list="dl-${tipo.slice(6)}"` : ""}
            ${["proc", "lote", "csg", "csp", "cse", "sdp", "plu", "ggn", "fda", "coc", "calibre"].includes(k) ? 'inputmode="numeric"' : ""}>
          <div class="nota"></div><div class="aviso"></div>
        </div>`).join("")}
    </div></fieldset>`).join("");
}

function getForm(prefijo) {
  const d = {};
  for (const k of CAMPOS) {
    const el = $(`#${prefijo}-${k}`);
    if (el && el.value.trim()) d[k] = el.value.trim();
  }
  return d;
}

function setForm(prefijo, datos, { limpiar = true } = {}) {
  for (const k of CAMPOS) {
    const el = $(`#${prefijo}-${k}`);
    if (!el) continue;
    if (datos[k] !== undefined && datos[k] !== null) el.value = datos[k];
    else if (limpiar) el.value = "";
  }
  limpiarMarcas(prefijo);
}

function limpiarMarcas(prefijo) {
  document.querySelectorAll(`#${prefijo}-form .fld`).forEach((f) => {
    delete f.dataset.estado; f.querySelector(".nota").textContent = ""; f.querySelector(".aviso").innerHTML = "";
  });
}

function datalists() {
  const dl = {
    especie: (maestros.especie?.filas || []).map((f) => f.especie),
    variedad: (maestros.variedad?.filas || []).map((f) => f.variedad),
    categoria: (maestros.categoria?.filas || []).map((f) => f.categoria),
    csg: (maestros.productor?.filas || []).map((f) => f.csg),
    sdp: (maestros.sdp?.filas || []).map((f) => f.sdp),
    csp: (maestros.planta?.filas || []).map((f) => f.csp),
    cse: (maestros.exportadora?.filas || []).map((f) => f.cse),
    embalaje: (maestros.embalaje?.filas || []).map((f) => f.codigo),
  };
  let cont = $("#datalists");
  if (!cont) { cont = document.createElement("div"); cont.id = "datalists"; document.body.appendChild(cont); }
  cont.innerHTML = Object.entries(dl).map(([k, v]) =>
    `<datalist id="dl-${k}">${[...new Set(v)].map((x) => `<option value="${esc(x)}">`).join("")}</datalist>`).join("");
}

function buscarMaestro(tabla, clave, valor) {
  const v = String(valor || "").trim().toUpperCase();
  return (maestros[tabla]?.filas || []).find((f) => String(f[clave]).toUpperCase() === v);
}

/** Completa desde maestros. Rellena vacíos y avisa cuando lo escrito/leído difiere del maestro. */
function autocompletar(prefijo, campoClave, { forzar = false } = {}) {
  const [tabla, clave, mapa] = AUTOCOMPLETAR[campoClave];
  const fila = buscarMaestro(tabla, clave, $(`#${prefijo}-${campoClave}`).value);
  const avisoClave = $(`#${prefijo}-fld-${campoClave} .aviso`);
  avisoClave.innerHTML = $(`#${prefijo}-${campoClave}`).value && !fila ? "No existe en maestros (se creará al guardar)" : "";
  if (!fila) return;
  for (const [campo, col] of Object.entries(mapa)) {
    const el = $(`#${prefijo}-${campo}`), valorM = fila[col];
    if (!el || !valorM) continue;
    const aviso = $(`#${prefijo}-fld-${campo} .aviso`);
    aviso.innerHTML = "";
    if (!el.value || forzar) el.value = valorM;
    else if (el.value.trim().toUpperCase() !== String(valorM).toUpperCase()) {
      aviso.innerHTML = `Maestro: ${esc(valorM)} <button type="button" class="btn chico">usar</button>`;
      aviso.querySelector("button").onclick = () => { el.value = valorM; aviso.innerHTML = ""; };
    }
  }
}

// ---------------- foto + OCR ----------------
async function procesarFoto(prefijo, archivo, etiquetaProgreso = "") {
  if (!archivo) return null;
  const prev = $(`#${prefijo}-preview`);
  prev.src = URL.createObjectURL(archivo); prev.hidden = false;
  const barra = $(`#${prefijo}-progreso`);
  barra.hidden = false;
  const progreso = (txt, p) => { barra.querySelector("span").textContent = `${etiquetaProgreso}${txt} ${p ? Math.round(p * 100) + "%" : ""}`;
    barra.querySelector("div").style.width = `${Math.round((p || 0) * 100)}%`; };
  try {
    if (typeof Tesseract === "undefined") throw new Error("No se pudo cargar el motor OCR (revisa la conexión a internet). Ingresa los datos a mano.");
    const r = await OCR.leer(archivo, maestros, progreso);
    return r;
  } catch (e) {
    toast(e.message, 5000);
    return null;
  } finally {
    barra.hidden = true;
  }
}

// ---------------- VALIDAR ----------------
function cargarSelectProcesos() {
  const activos = procesos.filter((p) => p.activo);
  const opc = activos.map((p) => `<option value="${p.id}">PROC ${esc(p.proc)} · LOTE ${esc(p.lote)} · ${esc(p.variedad || "")} · ${esc(p.fecha || "")}</option>`).join("");
  const sel = $("#v-proceso"), actual = sel.value;
  sel.innerHTML = `<option value="">Automático (según PROC y LOTE leídos)</option>${opc}`;
  sel.value = activos.some((p) => String(p.id) === actual) ? actual : "";
  const cop = $("#r-copiar");
  cop.innerHTML = `<option value="">—</option>` + procesos.map((p) => `<option value="${p.id}">PROC ${esc(p.proc)} · LOTE ${esc(p.lote)} · ${esc(p.variedad || "")}</option>`).join("");
}

async function validar(guardar = true) {
  const leido = getForm("v");
  if (!Object.keys(leido).length) { toast("Saca una foto o ingresa datos"); return; }
  try {
    const r = await api("/api/validar", { method: "POST", body: { leido, texto: ultimoTexto, proceso_id: $("#v-proceso").value || null, guardar } });
    mostrarResultado(r);
    return r;
  } catch (e) { toast("Error: " + e.message, 5000); return null; }
}

/** Foto original reducida a JPEG (máx. 2000 px) en dataURL. */
function aJpeg(archivo) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const esc = Math.min(1, 2000 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * esc); c.height = Math.round(img.height * esc);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL("image/jpeg", 0.9));
    };
    img.onerror = () => reject(new Error("No se pudo abrir la imagen"));
    img.src = URL.createObjectURL(archivo);
  });
}

/** Guarda la foto, el texto OCR, los campos leídos y el resultado en la carpeta etiquetas_leidas del servidor. */
async function guardarEtiquetaLeida(archivo, modo, lectura, resultado) {
  try {
    const res = resultado && { estado: resultado.estado, n_errores: resultado.n_errores, avisos: resultado.avisos,
      errores: resultado.filas.filter((f) => f.estado !== "ok" && f.estado !== "info" && f.estado !== "sin_referencia") };
    await api("/api/etiquetas", { method: "POST", body: { modo, imagen: await aJpeg(archivo), texto: lectura.texto,
      campos: lectura.campos, resultado: res } });
  } catch (e) { console.warn("No se guardó la etiqueta leída:", e.message); }
}

const ICONO_GRUPO = { ok: "✔", error: "✖", revisar: "⚠", sin_proceso: "–", sin_datos: "–" };
const TEXTO_GRUPO = { ok: "correcto", error: "con errores", revisar: "revisar", sin_proceso: "proceso no registrado", sin_datos: "sin datos" };

function mostrarResultado(r) {
  limpiarMarcas("v");
  const titulo = { ok: "✔ ETIQUETA CORRECTA", error: `✖ ETIQUETA CON ERRORES (${r.n_errores})`, revisar: "⚠ REVISAR: hay datos que no se leyeron bien" }[r.estado];
  const p = r.proceso;
  const sub = p ? `Proceso PROC ${esc(p.proc)} · LOTE ${esc(p.lote)} · ${esc(p.variedad || "")}` : "Proceso no registrado: se validan productor, planta y exportadora";
  const grupos = Object.values(r.grupos || {}).map((g) => `<div class="grupo ${g.estado}">
      <span class="ico">${ICONO_GRUPO[g.estado] || ""}</span><b>${esc(g.titulo)}</b>${g.clave ? ` <span class="clave">${esc(g.clave)}</span>` : ""}
      <small>${TEXTO_GRUPO[g.estado] || ""}</small></div>`).join("");
  const errGrupo = new Set(Object.values(r.grupos || {}).flatMap((g) => g.mensajes));
  const items = [];
  for (const f of r.filas) {
    if (f.estado === "error") items.push(`<li class="e"><b>${esc(f.titulo)}</b>: dice <b>${esc(f.leido)}</b>, debe decir <b>${esc(f.esperado)}</b></li>`);
  }
  for (const a of r.avisos) items.push(`<li class="${errGrupo.has(a) ? "e" : "w"}">${esc(a)}</li>`);
  for (const f of r.filas) {
    if (f.estado === "dudoso") items.push(`<li class="w"><b>${esc(f.titulo)}</b>: se lee parecido pero no igual a <b>${esc(f.esperado)}</b>. Revisa la etiqueta.</li>`);
    if (f.estado === "no_leido") items.push(`<li class="w"><b>${esc(f.titulo)}</b>: no se pudo leer (debe ser ${esc(f.esperado)}). Escríbelo y vuelve a validar.</li>`);
  }
  $("#v-resultado").innerHTML = `<div class="banner ${r.estado}">${titulo}<small>${sub}</small></div>` +
    `<div class="grupos">${grupos}</div>` + (items.length ? `<ul class="lista-err">${items.join("")}</ul>` : "");
  for (const f of r.filas) {
    const fld = $(`#v-fld-${f.campo}`);
    if (!fld || f.estado === "info" || f.estado === "sin_referencia") continue;
    fld.dataset.estado = f.estado === "dudoso" ? "no_leido" : f.estado;
    fld.querySelector(".nota").textContent =
      f.estado === "ok" ? `✔ correcto${f.nota ? " (" + f.nota + ")" : ""}` :
      f.estado === "error" ? `✖ debe ser: ${f.esperado}` :
      f.estado === "dudoso" ? `⚠ dudoso · debe ser: ${f.esperado}` : `falta · debe ser: ${f.esperado}`;
  }
  $("#v-resultado").scrollIntoView({ behavior: "smooth", block: "start" });
}

/**
 * Lee una o varias fotos de la MISMA etiqueta. Con `agregar` se suman a las ya leídas: los campos se votan
 * entre fotos y el servidor busca los valores de la base en el texto de todas, así lo que no se lee en una
 * se toma de otra.
 */
async function fotoValidar(archivos, agregar = false) {
  archivos = [...archivos].filter(Boolean);
  if (!archivos.length) return;
  if (!agregar) { lecturasV = []; $("#v-miniaturas").innerHTML = ""; }
  $("#v-resultado").innerHTML = "";
  const nuevas = [];
  for (const [i, archivo] of archivos.entries()) {
    const r = await procesarFoto("v", archivo, archivos.length > 1 ? `Foto ${i + 1} de ${archivos.length} · ` : "");
    if (!r) continue;
    const l = { ...r, archivo };
    lecturasV.push(l); nuevas.push(l);
    $("#v-miniaturas").insertAdjacentHTML("beforeend", `<img alt="" src="${URL.createObjectURL(archivo)}">`);
  }
  if (!lecturasV.length) return;
  setForm("v", OCR.votar(lecturasV.map((l) => l.campos)));
  ultimoTexto = lecturasV.map((l, i) => `===== FOTO ${i + 1} =====\n${l.texto}`).join("\n");
  $("#v-texto").textContent = ultimoTexto;
  $("#v-mas").hidden = false;
  $("#v-nfotos").textContent = lecturasV.length > 1 ? `${lecturasV.length} fotos de esta etiqueta combinadas.` : "1 foto leída.";
  const resultado = await validar(true);
  for (const l of nuevas) guardarEtiquetaLeida(l.archivo, "validacion", l, resultado);
}

function limpiarValidacion() {
  setForm("v", {}); lecturasV = []; ultimoTexto = "";
  $("#v-resultado").innerHTML = ""; $("#v-preview").hidden = true; $("#v-texto").textContent = "";
  $("#v-miniaturas").innerHTML = ""; $("#v-mas").hidden = true;
}

// ---------------- REGISTRAR ----------------
function modoRegistro() {
  $("#r-modo").textContent = editId
    ? `Editando proceso #${editId}. Al guardar se actualiza la etiqueta esperada.`
    : "Nuevo proceso: saca una foto de una etiqueta correcta para precargar los datos, o ingrésalos a mano.";
}

async function fotoRegistrar(archivo) {
  const r = await procesarFoto("r", archivo);
  if (!r) return;
  guardarEtiquetaLeida(archivo, "registro", r, null);
  setForm("r", r.campos, { limpiar: false });
  for (const k of Object.keys(AUTOCOMPLETAR)) if ($(`#r-${k}`).value) autocompletar("r", k);
  const faltan = SECCIONES.flatMap((s) => s.campos).filter(([k, , t]) => t !== "solo-registro" && k !== "calibre" && !$(`#r-${k}`).value).map((c) => c[1]);
  $("#r-mensaje").innerHTML = `<div class="msg ${faltan.length ? "warn" : "ok"}">Datos precargados desde la foto. Revisa cada campo antes de guardar.${faltan.length ? "<br>Faltan: " + esc(faltan.join(", ")) : ""}</div>`;
}

async function guardarProceso(actualizarMaestros = false) {
  const datos = getForm("r");
  if (!datos.proc || !datos.lote) { toast("PROC y LOTE son obligatorios"); return; }
  try {
    const r = await api("/api/procesos", { method: "POST", body: { datos, id: editId, actualizar_maestros: actualizarMaestros } });
    editId = r.proceso.id; modoRegistro();
    let html = `<div class="msg ok">Proceso PROC ${esc(r.proceso.proc)} / LOTE ${esc(r.proceso.lote)} guardado.`;
    if (r.maestros_creados.length) html += `<br>Maestros creados: ${esc(r.maestros_creados.join("; "))}`;
    html += "</div>";
    if (r.diferencias_maestros.length) {
      html += `<div class="msg warn">Estos datos difieren de los maestros (no se modificaron):<ul>${r.diferencias_maestros.map((d) =>
        `<li>${esc(d.tabla)} ${esc(d.clave)} · ${esc(d.campo)}: maestro <b>${esc(d.actual)}</b>, formulario <b>${esc(d.formulario)}</b></li>`).join("")}</ul>
        <button class="btn" id="r-act-maestros" type="button">Actualizar maestros con el formulario</button></div>`;
    }
    $("#r-mensaje").innerHTML = html;
    const b = $("#r-act-maestros");
    if (b) b.onclick = () => guardarProceso(true);
    await recargar();
    toast("Guardado");
  } catch (e) { $("#r-mensaje").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}

async function cargarEnRegistro(pid, copiar = false) {
  const d = await api(`/api/procesos/${pid}/esperado`);
  setForm("r", d);
  editId = copiar ? null : pid;
  if (copiar) { $("#r-proc").value = ""; $("#r-lote").value = ""; $("#r-observacion").value = ""; }
  modoRegistro();
  $("#r-mensaje").innerHTML = "";
}

// ---------------- PROCESOS ----------------
function renderProcesos() {
  const solo = $("#p-activos").checked;
  const lista = procesos.filter((p) => !solo || p.activo);
  $("#p-tabla").innerHTML = `<tr><th>PROC</th><th>Lote</th><th>Fecha</th><th>Variedad</th><th>CSG</th><th>SDP</th><th>Embalaje</th><th>Activo</th><th></th></tr>` +
    lista.map((p) => `<tr>
      <td>${esc(p.proc)}</td><td>${esc(p.lote)}</td><td>${esc(p.fecha)}</td><td>${esc(p.especie)} ${esc(p.variedad)}</td>
      <td>${esc(p.csg)}</td><td>${esc(p.sdp)}</td><td>${esc(p.embalaje)}</td>
      <td><input type="checkbox" data-act="${p.id}" ${p.activo ? "checked" : ""}></td>
      <td><button class="btn chico" data-edit="${p.id}">Editar</button>
          <button class="btn chico" data-val="${p.id}">Validar</button>
          <button class="btn chico peligro" data-del="${p.id}">Eliminar</button></td></tr>`).join("") ||
    `<tr><td colspan="9">Sin procesos</td></tr>`;
}

$("#p-tabla").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button, input"); if (!b) return;
  if (b.dataset.act) { await api(`/api/procesos/${b.dataset.act}/activo`, { method: "POST", body: { activo: b.checked } }); await recargar(); }
  if (b.dataset.edit) { await cargarEnRegistro(+b.dataset.edit); irA("registrar"); }
  if (b.dataset.val) { $("#v-proceso").value = b.dataset.val; irA("validar"); }
  if (b.dataset.del && confirm("¿Eliminar este proceso?")) { await api(`/api/procesos/${b.dataset.del}`, { method: "DELETE" }); await recargar(); }
});

// ---------------- MAESTROS ----------------
function renderMaestro() {
  const t = $("#m-tabla").value, m = maestros[t];
  if (!m) return;
  $("#m-orden").textContent = m.columnas.map((c) => c.titulo).join(" | ");
  const fila = (f, nueva) => `<tr data-nueva="${nueva ? 1 : ""}">${m.columnas.map((c) =>
    `<td><input data-c="${c.campo}" value="${esc(f[c.campo])}" ${!nueva && m.clave.includes(c.campo) ? "readonly" : ""}></td>`).join("")}
    <td><button class="btn chico" data-g>Guardar</button> <button class="btn chico peligro" data-x>✕</button></td></tr>`;
  $("#m-grilla").innerHTML = `<tr>${m.columnas.map((c) => `<th>${esc(c.titulo)}</th>`).join("")}<th></th></tr>` +
    m.filas.map((f) => fila(f, false)).join("");
  renderMaestro.fila = fila;
}

$("#m-grilla").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button"); if (!b) return;
  const tr = b.closest("tr"), t = $("#m-tabla").value;
  const datos = Object.fromEntries([...tr.querySelectorAll("input")].map((i) => [i.dataset.c, i.value]));
  try {
    if (b.hasAttribute("data-g")) { await api(`/api/maestros/${t}`, { method: "POST", body: datos }); toast("Guardado"); await recargar(); }
    if (b.hasAttribute("data-x")) {
      if (tr.dataset.nueva) { tr.remove(); return; }
      if (!confirm("¿Eliminar esta fila?")) return;
      await api(`/api/maestros/${t}/eliminar`, { method: "POST", body: datos }); await recargar();
    }
  } catch (e) { toast("Error: " + e.message, 4000); }
});

$("#m-agregar").onclick = () => {
  $("#m-grilla").insertAdjacentHTML("beforeend", renderMaestro.fila({}, true));
};

$("#m-importar").onclick = async () => {
  const t = $("#m-tabla").value, cols = maestros[t].columnas.map((c) => c.campo);
  const lineas = $("#m-pegar").value.split(/\r?\n/).filter((l) => l.trim());
  let ok = 0, err = 0;
  for (const l of lineas) {
    const v = l.split("\t");
    try { await api(`/api/maestros/${t}`, { method: "POST", body: Object.fromEntries(cols.map((c, i) => [c, (v[i] || "").trim()])) }); ok++; }
    catch (e) { err++; }
  }
  toast(`Importadas ${ok} filas${err ? `, ${err} con error` : ""}`, 4000);
  $("#m-pegar").value = "";
  await recargar();
};

// ---------------- HISTORIAL ----------------
async function renderHistorial() {
  const h = await api("/api/historial");
  $("#h-lista").innerHTML = h.map((v) => {
    const errs = (v.detalle.filas || []).filter((f) => f.estado === "error")
      .map((f) => `<li>${esc(f.titulo)}: dice ${esc(f.leido)}, debe ser ${esc(f.esperado)}</li>`).join("") +
      (v.detalle.avisos || []).map((a) => `<li>${esc(a)}</li>`).join("");
    return `<details class="hist"><summary><span class="chip ${v.resultado}">${v.resultado.toUpperCase()}</span>
      ${esc(v.fecha_hora.replace("T", " "))} · PROC ${esc(v.proc || "?")} · LOTE ${esc(v.lote || "?")}
      ${v.errores ? `· ${v.errores} error(es)` : ""}</summary>${errs ? `<ul>${errs}</ul>` : "<p>Sin errores</p>"}</details>`;
  }).join("") || "<p>Sin validaciones</p>";
}

// ---------------- general ----------------
function irA(tab) {
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("activo", b.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("activo", s.id === `tab-${tab}`));
  if (tab === "historial") renderHistorial();
  window.scrollTo(0, 0);
}

async function recargar() {
  [maestros, procesos] = await Promise.all([api("/api/maestros"), api("/api/procesos")]);
  datalists(); cargarSelectProcesos(); renderProcesos();
  const sel = $("#m-tabla");
  if (!sel.options.length) sel.innerHTML = Object.entries(maestros).map(([k, m]) => `<option value="${k}">${esc(m.titulo)}</option>`).join("");
  renderMaestro();
}

function init() {
  renderForm("v", false);
  renderForm("r", true);
  document.querySelectorAll("nav button").forEach((b) => (b.onclick = () => irA(b.dataset.tab)));

  for (const id of ["v-foto", "v-galeria"]) $(`#${id}`).onchange = (e) => { fotoValidar(e.target.files); e.target.value = ""; };
  $("#v-otra").onchange = (e) => { fotoValidar(e.target.files, true); e.target.value = ""; };
  for (const id of ["r-foto", "r-galeria"]) $(`#${id}`).onchange = (e) => { fotoRegistrar(e.target.files[0]); e.target.value = ""; };
  $("#v-validar").onclick = () => validar(true);
  $("#v-limpiar").onclick = limpiarValidacion;
  $("#r-guardar").onclick = () => guardarProceso(false);
  $("#r-nuevo").onclick = () => { editId = null; setForm("r", {}); $("#r-mensaje").innerHTML = ""; $("#r-preview").hidden = true; modoRegistro(); };
  $("#r-copiar").onchange = (e) => { if (e.target.value) cargarEnRegistro(+e.target.value, true); e.target.value = ""; };
  for (const k of Object.keys(AUTOCOMPLETAR)) $(`#r-${k}`).addEventListener("change", () => autocompletar("r", k));
  $("#p-activos").onchange = renderProcesos;
  $("#m-tabla").onchange = renderMaestro;
  $("#h-recargar").onclick = renderHistorial;
  $("#cfg-fecha").value = OCR.getFormatoFecha();
  $("#cfg-fecha").onchange = (e) => { OCR.setFormatoFecha(e.target.value); toast("Formato de fecha guardado en este dispositivo"); };
  arrancar();
}

// ---------------- configuración inicial (primera vez) ----------------
function datosConfig() {
  return { servidor: $("#cfg-servidor").value.trim(), puerto: $("#cfg-puerto").value.trim(),
    base: $("#cfg-base").value.trim(), windows: $("#cfg-windows").checked, usuario: $("#cfg-usuario").value.trim(),
    clave: $("#cfg-clave").value, confiar_certificado: $("#cfg-cert").checked };
}

function mostrarConfiguracion(estado) {
  document.querySelectorAll(".tab, header nav").forEach((e) => (e.hidden = true));
  $("#config-inicial").hidden = false;
  if (estado.error) $("#cfg-error").innerHTML = `<div class="msg err">${esc(estado.error)}</div>`;
  if (estado.servidor) $("#cfg-servidor").value = estado.servidor;
  if (estado.base) $("#cfg-base").value = estado.base;
  const sql = () => document.querySelectorAll(".cfg-sql").forEach((e) => (e.hidden = $("#cfg-windows").checked));
  $("#cfg-windows").onchange = sql;
  const msg = (cls, t) => ($("#cfg-msg").innerHTML = `<div class="msg ${cls}">${esc(t)}</div>`);
  $("#cfg-probar").onclick = async () => {
    msg("warn", "Probando conexión…");
    try { const r = await api("/api/config/probar", { method: "POST", body: datosConfig() }); msg(r.ok ? "ok" : "err", r.mensaje); }
    catch (e) { msg("err", e.message); }
  };
  $("#cfg-guardar").onclick = async () => {
    msg("warn", "Creando base de datos y tablas…");
    $("#cfg-guardar").disabled = true;
    try {
      await api("/api/config", { method: "POST", body: datosConfig() });
      msg("ok", "Listo. Base y tablas creadas.");
      setTimeout(() => location.reload(), 800);
    } catch (e) { msg("err", e.message); $("#cfg-guardar").disabled = false; }
  };
}

async function arrancar() {
  try {
    const estado = await api("/api/config/estado");
    if (!estado.configurado) { mostrarConfiguracion(estado); return; }
    await recargar();
  } catch (e) { toast("No se pudo conectar con el servidor: " + e.message, 6000); }
}

init();
