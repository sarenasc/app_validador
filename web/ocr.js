/* Lectura de la etiqueta: preprocesa la foto, hace OCR (Tesseract.js en el navegador) y extrae los campos. */
"use strict";

const OCR = (() => {
  const N = "[0-9OQDIL|SB]"; // dígito o confusión típica del OCR
  const MAPA = { O: "0", Q: "0", D: "0", I: "1", L: "1", "|": "1", S: "5", B: "8" };
  const fixNum = (s) => (s || "").toUpperCase().replace(/[OQDIL|SB]/g, (c) => MAPA[c]).replace(/\D/g, "");
  const norm = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
  const compacto = (s) => norm(s).replace(/[^A-Z0-9]/g, "");

  // Formato de la fecha impresa: "MDY" (11/18/26 = 18 nov) o "DMY"
  let formatoFecha = "MDY";
  try { formatoFecha = localStorage.getItem("formatoFecha") || "MDY"; } catch (e) { /* sin storage */ }

  function num(texto, etiqueta, min, max) {
    const re = new RegExp(`${etiqueta}\\s*[:;.,]?\\s*(${N}{1,${max + 2}})`);
    const m = texto.match(re);
    if (!m) return "";
    const d = fixNum(m[1]);
    return d.length >= min ? d.slice(0, max) : "";
  }

  function fechaISO(a, b, c, formato) {
    let [m, d] = formato === "DMY" ? [b, a] : [a, b];
    if (+m > 12 && +d <= 12) [m, d] = [d, m];
    let y = c.length === 2 ? "20" + c : c;
    if (+m < 1 || +m > 12 || +d < 1 || +d > 31) return "";
    return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  }

  function buscarEnCatalogo(textoCompacto, opciones) {
    // opciones: [{valor, alias:[...]}]; devuelve el alias más largo encontrado
    let mejor = null, largo = 0;
    for (const o of opciones) {
      for (const a of o.alias) {
        const c = compacto(a);
        if (c.length >= 3 && c.length > largo && textoCompacto.includes(c)) { mejor = o.valor; largo = c.length; }
      }
    }
    return mejor || "";
  }

  /** Extrae los campos desde el texto OCR. `cat` = maestros (de /api/maestros). */
  function parsear(textoOriginal, cat) {
    const t = norm(textoOriginal).replace(/[“”"]/g, "");
    const tc = compacto(t);
    const r = {};
    const filas = (k) => (cat && cat[k] ? cat[k].filas : []);

    r.csg = num(t, "C[S5]G", 4, 8);
    r.csp = num(t, "[CE][S5]P", 4, 8);
    r.cse = num(t, "[CE][S5]E", 3, 8);
    r.ggn = num(t, "GGN", 13, 13);
    r.fda = num(t, "FDA", 8, 12);
    r.coc = num(t, "C[O0]C", 13, 13);
    r.proc = num(t, "PR[O0]C", 1, 5);
    r.lote = num(t, "L[O0]TE", 1, 6);
    r.sdp = num(t, "[S5]DP", 3, 8);
    r.plu = num(t, "PLU", 3, 5);

    let m = t.match(/(\d+[.,]\d+|\d+)\s*K\s*G/);
    if (m) r.peso_kg = m[1].replace(",", ".");
    m = t.match(/(\d+[.,]\d+|\d+)\s*[LI|]\s*B[S]?\b/); // "lb" suele leerse como "Ib"
    if (m) r.peso_lb = m[1].replace(",", ".");

    // Fecha impresa; si no se lee, se usa el código GS1 (13)AAMMDD
    m = t.match(/(?:EMBALAJE|PACK DATE)[^\d]{0,40}(\d{1,2})\s*[\/\-.]\s*(\d{1,2})\s*[\/\-.]\s*(\d{2,4})/) ||
        t.match(/\b(\d{1,2})\s*\/\s*(\d{1,2})\s*\/\s*(\d{2,4})\b/);
    if (m) r.fecha = fechaISO(m[1], m[2], m[3], formatoFecha);
    if (!r.fecha && (m = t.replace(/\s/g, "").match(/\(13\)(\d{2})(\d{2})(\d{2})/))) r.fecha = `20${m[1]}-${m[2]}-${m[3]}`;
    // CSG desde GS1 (10) si no se leyó
    if (!r.csg && (m = t.replace(/\s/g, "").match(/\(10\)(\d{4,8})/))) r.csg = m[1];

    // Región / provincia / comuna (1ª ocurrencia = productor, 2ª = planta)
    const regs = [...t.matchAll(/(\d{1,2}|\b[IVX]{1,4})\s*\/\s*([A-ZÑ' ]{3,}?)\s*\/\s*([A-ZÑ']{3,}(?: [A-ZÑ']{3,})*)/g)];
    if (regs[0]) [r.prod_region, r.prod_provincia, r.prod_comuna] = [regs[0][1], regs[0][2].trim(), regs[0][3].trim()];
    if (regs[1]) [r.planta_region, r.planta_provincia, r.planta_comuna] = [regs[1][1], regs[1][2].trim(), regs[1][3].trim()];
    const corta = (s) => s && s.replace(/\s+(C[S5][EGP]|GGN|FDA|C[O0]C|EXPORTADORA|PROC|LOTE|SDP)\b.*$/, "").trim();
    for (const k of ["prod_provincia", "prod_comuna", "planta_provincia", "planta_comuna"]) r[k] = corta(r[k]);

    // Categoría
    const cats = filas("categoria").map((f) => ({ valor: f.categoria, alias: [f.categoria] }));
    r.categoria = buscarEnCatalogo(tc, cats);
    if (!r.categoria && (m = t.match(/\bCAT\s*[:.]?\s*([0-9IL|]{1,2}|EXTRA|PREMIUM)\b/))) {
      r.categoria = "CAT " + (/\d|[IL|]/.test(m[1]) ? fixNum(m[1]) : m[1]);
    }

    // Especie / variedad / exportadora / embalaje: se buscan en los maestros
    r.especie = buscarEnCatalogo(tc, filas("especie").map((f) => ({ valor: f.especie, alias: [f.especie, f.nombre_ingles].filter(Boolean) })));
    const vars = filas("variedad").filter((f) => !r.especie || f.especie === r.especie);
    r.variedad = buscarEnCatalogo(tc, vars.map((f) => ({ valor: f.variedad, alias: [f.variedad] })));
    r.exportadora = buscarEnCatalogo(tc, filas("exportadora").map((f) => ({ valor: f.nombre, alias: [f.nombre] })));
    if (!r.exportadora && (m = t.match(/(EXPORTADORA\s+[A-Z][A-Z .&]{3,40})/))) r.exportadora = m[1].trim();
    const tc0 = tc.replace(/O/g, "0");
    for (const f of filas("embalaje")) {
      if (tc0.includes(compacto(f.codigo).replace(/O/g, "0"))) { r.embalaje = f.codigo; break; }
    }
    if (!r.embalaje && (m = t.match(/EMBALAJE[^A-Z0-9]{0,10}(?:[A-Z ]{0,20}\n)?\s*([A-Z]{2,4}[0-9O]{2,4}[A-Z0-9]{3,12})/))) r.embalaje = m[1];
    if (!r.embalaje && (m = t.match(/\b([A-Z]{2,4}[0-9O]{2,4}[A-Z]{1,3}[0-9O]{1,3}[A-Z]{1,4})\b/))) r.embalaje = m[1];

    m = t.match(/CALIBRE\s*\n?\s*(\d{1,3})\b/);
    if (m) r.calibre = m[1];

    for (const k of Object.keys(r)) if (!r[k]) delete r[k];
    return r;
  }

  /** Escala, pasa a gris y estira el contraste. Devuelve un canvas. */
  function preprocesar(archivo) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const max = 2400, esc = Math.min(1, max / Math.max(img.width, img.height)) * (Math.max(img.width, img.height) < 1400 ? 1.8 : 1);
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * esc); c.height = Math.round(img.height * esc);
        const ctx = c.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0, c.width, c.height);
        const d = ctx.getImageData(0, 0, c.width, c.height), p = d.data;
        const hist = new Uint32Array(256);
        for (let i = 0; i < p.length; i += 4) {
          const g = (p[i] * 0.299 + p[i + 1] * 0.587 + p[i + 2] * 0.114) | 0;
          p[i] = g; hist[g]++;
        }
        // percentiles 2% y 98% para estirar contraste
        const total = p.length / 4; let acc = 0, lo = 0, hi = 255;
        for (let i = 0; i < 256; i++) { acc += hist[i]; if (acc > total * 0.02) { lo = i; break; } }
        acc = 0;
        for (let i = 255; i >= 0; i--) { acc += hist[i]; if (acc > total * 0.02) { hi = i; break; } }
        const rango = Math.max(1, hi - lo);
        for (let i = 0; i < p.length; i += 4) {
          const v = Math.max(0, Math.min(255, ((p[i] - lo) * 255) / rango));
          p[i] = p[i + 1] = p[i + 2] = v;
        }
        ctx.putImageData(d, 0, 0);
        URL.revokeObjectURL(img.src);
        resolve(c);
      };
      img.onerror = () => reject(new Error("No se pudo abrir la imagen"));
      img.src = URL.createObjectURL(archivo);
    });
  }

  let worker = null;
  async function obtenerWorker(progreso) {
    if (!worker) {
      progreso && progreso("Cargando motor de lectura (solo la primera vez)…", 0);
      worker = await Tesseract.createWorker("eng", 1, {
        logger: (m) => progreso && m.status === "recognizing text" && progreso("Leyendo etiqueta…", m.progress),
      });
    }
    return worker;
  }

  const CLAVES = ["csg", "csp", "cse", "ggn", "fda", "coc", "proc", "lote", "sdp", "embalaje", "fecha", "variedad",
    "especie", "exportadora", "peso_kg", "peso_lb", "plu", "categoria", "prod_comuna", "planta_comuna"];

  /** Lee la foto y devuelve {campos, texto}. Si faltan campos hace una 2ª pasada (texto disperso) y une ambos textos. */
  async function leer(archivo, catalogo, progreso) {
    const canvas = await preprocesar(archivo);
    const w = await obtenerWorker(progreso);
    await w.setParameters({ tessedit_pageseg_mode: "3" });
    let { data } = await w.recognize(canvas, { rotateAuto: true });
    let texto = data.text;
    let campos = parsear(texto, catalogo);
    if (CLAVES.some((k) => !campos[k])) {
      progreso && progreso("Segunda lectura para completar campos…", 0);
      await w.setParameters({ tessedit_pageseg_mode: "11" });
      ({ data } = await w.recognize(canvas, { rotateAuto: true }));
      texto += "\n----- 2ª lectura -----\n" + data.text;
      campos = { ...parsear(data.text, catalogo), ...parsear(texto, catalogo) };
    }
    return { campos, texto };
  }

  return { leer, parsear, fixNum, setFormatoFecha: (f) => { formatoFecha = f; try { localStorage.setItem("formatoFecha", f); } catch (e) { /* */ } }, getFormatoFecha: () => formatoFecha };
})();

if (typeof module !== "undefined") module.exports = OCR;
