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
    const canon = (x) => x.replace(/[OQDIL|SBZG]/g, (c) => ({ ...MAPA, Z: "2", G: "6" })[c]); // O/0, S/5, I/1, B/8...
    const tc0 = canon(tc);
    for (const f of filas("embalaje")) {
      if (tc0.includes(canon(compacto(f.codigo)))) { r.embalaje = f.codigo; break; }
    }
    if (!r.embalaje && (m = t.match(/EMBALAJE[^A-Z0-9]{0,10}(?:[A-Z ]{0,20}\n)?\s*([A-Z]{2,4}[0-9O]{2,4}[A-Z0-9]{3,12})/))) r.embalaje = m[1];
    if (!r.embalaje && (m = t.match(/\b([A-Z]{2,4}[0-9O]{2,4}[A-Z]{1,3}[0-9O]{1,3}[A-Z]{1,4})\b/))) r.embalaje = m[1];

    m = t.match(/CALIBRE\s*\n?\s*(\d{1,3})\b/);
    if (m) r.calibre = m[1];

    for (const k of Object.keys(r)) if (!r[k]) delete r[k];
    return r;
  }

  /** Busca el rectángulo claro de la etiqueta (fondo oscuro alrededor). Devuelve {x,y,w,h} en px de la imagen o null. */
  function ubicarEtiqueta(img) {
    const esc = Math.min(1, 500 / Math.max(img.width, img.height));
    const w = Math.max(1, Math.round(img.width * esc)), h = Math.max(1, Math.round(img.height * esc));
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, w, h);
    const p = ctx.getImageData(0, 0, w, h).data, g = new Uint8Array(w * h), hist = new Uint32Array(256);
    for (let i = 0; i < w * h; i++) { g[i] = (p[i * 4] * 0.299 + p[i * 4 + 1] * 0.587 + p[i * 4 + 2] * 0.114) | 0; hist[g[i]]++; }
    // umbral de Otsu
    let sum = 0; for (let i = 0; i < 256; i++) sum += i * hist[i];
    let sB = 0, wB = 0, mejor = 0, t = 128;
    for (let i = 0; i < 256; i++) {
      wB += hist[i]; if (!wB) continue; const wF = w * h - wB; if (!wF) break;
      sB += i * hist[i]; const mB = sB / wB, mF = (sum - sB) / wF, v = wB * wF * (mB - mF) ** 2;
      if (v > mejor) { mejor = v; t = i; }
    }
    const tramo = (perfil, largo, umbral) => {  // tramo más largo sobre el umbral, tolerando huecos cortos
      let best = [0, -1], ini = -1, hueco = 0;
      const gapMax = Math.round(largo * 0.04);
      for (let i = 0; i <= largo; i++) {
        if (i < largo && perfil[i] > umbral) { if (ini < 0) ini = i; hueco = 0; continue; }
        if (ini < 0) continue;
        hueco++;
        if (hueco > gapMax || i === largo) {
          const fin = i - hueco;
          if (fin - ini > best[1] - best[0]) best = [ini, fin];
          ini = -1; hueco = 0;
        }
      }
      return best;
    };
    const filas = new Float32Array(h), cols = new Float32Array(w);
    for (let y = 0; y < h; y++) { let n = 0; for (let x = 0; x < w; x++) n += g[y * w + x] > t; filas[y] = n / w; }
    const [y0, y1] = tramo(filas, h, 0.35);
    if (y1 <= y0) return null;
    for (let x = 0; x < w; x++) { let n = 0; for (let y = y0; y <= y1; y++) n += g[y * w + x] > t; cols[x] = n / (y1 - y0 + 1); }
    const [x0, x1] = tramo(cols, w, 0.35);
    const area = ((x1 - x0) * (y1 - y0)) / (w * h);
    if (x1 <= x0 || area < 0.08 || area > 0.92) return null;  // sin recorte claro: se usa la foto completa
    const m = 0.02 * Math.max(w, h);
    const X0 = Math.max(0, x0 - m), Y0 = Math.max(0, y0 - m), X1 = Math.min(w, x1 + m), Y1 = Math.min(h, y1 + m);
    return { x: X0 / esc, y: Y0 / esc, w: (X1 - X0) / esc, h: (Y1 - Y0) / esc };
  }

  /** Recorta la etiqueta, la amplía (lado mayor ~2400 px), pasa a gris y estira el contraste. Devuelve un canvas. */
  function preprocesar(archivo) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const r = ubicarEtiqueta(img) || { x: 0, y: 0, w: img.width, h: img.height };
        const esc = Math.min(2.5, 2400 / Math.max(r.w, r.h));
        const c = document.createElement("canvas");
        c.width = Math.round(r.w * esc); c.height = Math.round(r.h * esc);
        const ctx = c.getContext("2d", { willReadFrequently: true });
        ctx.imageSmoothingQuality = "high";
        ctx.drawImage(img, r.x, r.y, r.w, r.h, 0, 0, c.width, c.height);
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

  /** Blanco y negro adaptativo (umbral local de Bradley): ayuda con sombras y etiquetas arrugadas. */
  function binarizar(src) {
    const w = src.width, h = src.height;
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(src, 0, 0);
    const d = ctx.getImageData(0, 0, w, h), p = d.data, W = w + 1;
    const integ = new Float64Array(W * (h + 1));
    for (let y = 1; y <= h; y++) {
      let fila = 0;
      for (let x = 1; x <= w; x++) { fila += p[((y - 1) * w + x - 1) * 4]; integ[y * W + x] = integ[(y - 1) * W + x] + fila; }
    }
    const r = Math.max(8, Math.round(w / 40));
    for (let y = 0; y < h; y++) {
      const ya = Math.max(0, y - r), yb = Math.min(h, y + r + 1);
      for (let x = 0; x < w; x++) {
        const xa = Math.max(0, x - r), xb = Math.min(w, x + r + 1);
        const s = integ[yb * W + xb] - integ[ya * W + xb] - integ[yb * W + xa] + integ[ya * W + xa];
        const i = (y * w + x) * 4, v = p[i] * (xb - xa) * (yb - ya) < s * 0.85 ? 0 : 255;
        p[i] = p[i + 1] = p[i + 2] = v;
      }
    }
    ctx.putImageData(d, 0, 0);
    return c;
  }

  /** Por cada campo elige el valor que más se repite entre las lecturas (a igualdad, el de la primera). */
  function votar(lecturas) {
    const out = {};
    for (const k of new Set(lecturas.flatMap((l) => Object.keys(l)))) {
      const cuenta = new Map();
      for (const l of lecturas) if (l[k]) cuenta.set(l[k], (cuenta.get(l[k]) || 0) + 1);
      let mejor = null, n = 0;
      for (const [v, c] of cuenta) if (c > n) { mejor = v; n = c; }
      if (mejor) out[k] = mejor;
    }
    return out;
  }

  /** Lee la foto: hasta 3 pasadas (gris por bloques, blanco y negro disperso, gris disperso) y vota los campos. */
  async function leer(archivo, catalogo, progreso) {
    const gris = await preprocesar(archivo);
    const w = await obtenerWorker(progreso);
    const pasadas = [["3", false, "1ª lectura"], ["11", true, "2ª lectura (blanco y negro)"], ["11", false, "3ª lectura"]];
    const textos = [], lecturas = [];
    const combinar = () => ({ ...parsear(textos.join("\n"), catalogo), ...votar(lecturas) });
    for (const [psm, bn, nombre] of pasadas) {
      if (lecturas.length && CLAVES.every((k) => combinar()[k])) break;
      progreso && progreso(`${nombre}…`, 0);
      await w.setParameters({ tessedit_pageseg_mode: psm });
      const { data } = await w.recognize(bn ? binarizar(gris) : gris, { rotateAuto: true });
      textos.push(`----- ${nombre} -----\n${data.text}`);
      lecturas.push(parsear(data.text, catalogo));
    }
    return { campos: combinar(), texto: textos.join("\n") };
  }

  return { leer, parsear, fixNum, setFormatoFecha: (f) => { formatoFecha = f; try { localStorage.setItem("formatoFecha", f); } catch (e) { /* */ } }, getFormatoFecha: () => formatoFecha };
})();

if (typeof module !== "undefined") module.exports = OCR;
