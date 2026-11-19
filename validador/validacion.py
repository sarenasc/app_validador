"""Compara los datos leídos de una etiqueta contra el proceso registrado y los maestros.

`leido` es un dict con las claves de CAMPOS (todas opcionales). El calibre se muestra pero no se valida.
"""

import re
import unicodedata

from . import db

# campo -> (título, tipo de comparación)
CAMPOS = {
    "especie": ("Especie", "texto"),
    "variedad": ("Variedad", "texto"),
    "csg": ("CSG productor", "num"),
    "prod_region": ("Región productor", "region"),
    "prod_provincia": ("Provincia productor", "texto"),
    "prod_comuna": ("Comuna productor", "texto"),
    "ggn": ("GGN", "num"),
    "csp": ("CSP planta", "num"),
    "planta_region": ("Región planta", "region"),
    "planta_provincia": ("Provincia planta", "texto"),
    "planta_comuna": ("Comuna planta", "texto"),
    "fda": ("FDA", "num"),
    "coc": ("CoC", "num"),
    "cse": ("CSE exportadora", "num"),
    "exportadora": ("Exportadora", "texto"),
    "proc": ("PROC", "num"),
    "lote": ("Lote", "num"),
    "sdp": ("SDP (sitio de producción)", "num"),
    "embalaje": ("Embalaje", "codigo"),
    "peso_kg": ("Peso neto kg", "peso"),
    "peso_lb": ("Peso neto lb", "peso"),
    "plu": ("PLU", "num"),
    "fecha": ("Fecha embalaje", "fecha"),
    "categoria": ("Categoría", "texto"),
    "calibre": ("Calibre (no se valida)", "info"),
}

ROMANOS = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
           "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "RM": 13}
_OCR_DIGITOS = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1", "S": "5",
                              "B": "8", "Z": "2", "G": "6"})


def norm_texto(v):
    v = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]", "", v)


def norm_num(v):
    v = str(v or "").upper().replace(" ", "")
    if not v:
        return ""
    # solo corrige confusiones típicas de OCR si el valor es mayoritariamente numérico
    if sum(ch.isdigit() for ch in v) >= len(v) / 2:
        v = v.translate(_OCR_DIGITOS)
    v = re.sub(r"\D", "", v)
    return v.lstrip("0") or ("0" if v else "")


def norm_region(v):
    t = norm_texto(v)
    if t in ROMANOS:
        return str(ROMANOS[t])
    return norm_num(t)


def norm_peso(v):
    try:
        return round(float(str(v).replace(",", ".").strip()), 2)
    except (TypeError, ValueError):
        return None


def _distancia(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def comparar(tipo, leido, esperado):
    """Devuelve (coincide: bool, nota: str|None)."""
    if tipo == "num":
        return norm_num(leido) == norm_num(esperado), None
    if tipo == "region":
        return norm_region(leido) == norm_region(esperado), None
    if tipo == "peso":
        a, b = norm_peso(leido), norm_peso(esperado)
        return a is not None and b is not None and abs(a - b) <= 0.02, None
    if tipo == "fecha":
        return str(leido).strip() == str(esperado).strip(), None
    if tipo == "codigo":
        a, b = norm_texto(leido), norm_texto(esperado)
        if a == b:
            return True, None
        # O/0 confundidos por OCR en códigos alfanuméricos
        return a.replace("O", "0") == b.replace("O", "0"), "lectura aproximada (O/0)"
    a, b = norm_texto(leido), norm_texto(esperado)
    if a == b or (b and b in a and len(a) - len(b) <= 3):
        return True, None
    if len(b) >= 6 and _distancia(a, b) <= 1:
        return True, "lectura aproximada"
    return False, None


def _peso_lb(peso_kg):
    p = norm_peso(peso_kg)
    return None if p is None else round(p * 2.20462, 2)


def esperados(proceso, leido, obtener=db.obtener):
    """Arma el dict campo -> (valor esperado, origen) desde el proceso y los maestros."""
    base = proceso or {}
    esp = {}
    for c in ("proc", "lote", "fecha", "csg", "sdp", "csp", "cse", "embalaje", "especie", "variedad",
              "categoria", "plu"):
        if base.get(c):
            esp[c] = (base[c], "proceso")

    # Clave para buscar en maestros: la del proceso, o la leída si no hay proceso
    def clave(c):
        return base.get(c) or (norm_num(leido.get(c)) if leido.get(c) else None)

    csg, csp, cse, emb = clave("csg"), clave("csp"), clave("cse"), base.get("embalaje") or leido.get("embalaje")
    if csg and (p := obtener("productor", csg=str(csg).upper())):
        for c, m in (("prod_region", "region"), ("prod_provincia", "provincia"),
                     ("prod_comuna", "comuna"), ("ggn", "ggn")):
            if p.get(m):
                esp[c] = (p[m], "maestro productor")
    if csp and (p := obtener("planta", csp=str(csp).upper())):
        for c, m in (("planta_region", "region"), ("planta_provincia", "provincia"),
                     ("planta_comuna", "comuna"), ("fda", "fda"), ("coc", "coc")):
            if p.get(m):
                esp[c] = (p[m], "maestro planta")
    if cse and (e := obtener("exportadora", cse=str(cse).upper())):
        if e.get("nombre"):
            esp["exportadora"] = (e["nombre"], "maestro exportadora")
    if emb and (e := obtener("embalaje", codigo=norm_texto(emb))):
        if e.get("peso_kg"):
            esp["peso_kg"] = (e["peso_kg"], "maestro embalaje")
            esp["peso_lb"] = (e.get("peso_lb") or _peso_lb(e["peso_kg"]), "maestro embalaje")
        if e.get("plu") and "plu" not in esp:
            esp["plu"] = (e["plu"], "maestro embalaje")
    return esp


CAMPOS_IDENTIFICAN = ("proc", "lote", "csg", "sdp", "csp", "cse", "embalaje", "variedad", "fecha", "categoria", "plu")


def mejor_proceso(leido, procesos):
    """Busca entre los procesos de la base el que más coincide con lo leído.

    Devuelve (proceso, texto con los campos coincidentes) o (None, None) si no hay uno claro:
    se exigen al menos 3 coincidencias y que no haya empate con otro proceso.
    """
    puntajes = []
    for p in procesos:
        iguales = [c for c in CAMPOS_IDENTIFICAN
                   if leido.get(c) and p.get(c) and comparar(CAMPOS[c][1], leido[c], p[c])[0]]
        puntajes.append((len(iguales), iguales, p))
    puntajes.sort(key=lambda x: -x[0])
    if not puntajes or puntajes[0][0] < 3 or (len(puntajes) > 1 and puntajes[1][0] == puntajes[0][0]):
        return None, None
    n, iguales, p = puntajes[0]
    return p, ", ".join(CAMPOS[c][0] for c in iguales)


def validar(leido, proceso=None, obtener=db.obtener):
    leido = {k: (str(v).strip() if v not in (None, "") else "") for k, v in (leido or {}).items()}
    esp = esperados(proceso, leido, obtener)
    filas, avisos = [], []

    if proceso is None:
        avisos.append("No hay un proceso registrado para PROC "
                      f"{leido.get('proc') or '?'} / LOTE {leido.get('lote') or '?'}: "
                      "solo se valida contra los maestros.")

    for campo, (titulo, tipo) in CAMPOS.items():
        valor = leido.get(campo, "")
        esperado, origen = esp.get(campo, (None, None))
        fila = {"campo": campo, "titulo": titulo, "leido": valor, "esperado": esperado, "origen": origen,
                "nota": None}
        if tipo == "info":
            fila["estado"] = "info"
        elif esperado in (None, ""):
            fila["estado"] = "sin_referencia"
        elif not valor:
            fila["estado"] = "no_leido"
        else:
            ok, nota = comparar(tipo, valor, esperado)
            fila["estado"] = "ok" if ok else "error"
            fila["nota"] = nota if ok else None
        filas.append(fila)

    # Consistencia con maestros (relaciones)
    def relacion(tabla, msg, **clave):
        if all(clave.values()) and obtener(tabla, **clave) is None:
            avisos.append(msg)
            return False
        return True

    errores_rel = 0
    especie = (proceso or {}).get("especie") or leido.get("especie")
    variedad = leido.get("variedad")
    if especie and variedad and not relacion("variedad", f"La variedad {variedad} no está registrada para "
                                                         f"{especie}.", especie=especie.upper(),
                                             variedad=variedad.upper()):
        errores_rel += 1
    csg = norm_num(leido.get("csg")) or (proceso or {}).get("csg")
    sdp = norm_num(leido.get("sdp"))
    if csg and sdp and not relacion("sdp", f"El SDP {sdp} no está registrado para el CSG {csg}.", csg=csg, sdp=sdp):
        errores_rel += 1
    if not proceso:
        if leido.get("csg") and "ggn" not in esp:
            avisos.append(f"El CSG {norm_num(leido['csg'])} no existe en el maestro de productores.")
        if leido.get("csp") and "fda" not in esp:
            avisos.append(f"El CSP {norm_num(leido['csp'])} no existe en el maestro de plantas.")

    n_err = sum(f["estado"] == "error" for f in filas) + errores_rel + (1 if proceso is None else 0)
    n_nl = sum(f["estado"] == "no_leido" for f in filas)
    estado = "error" if n_err else ("revisar" if n_nl else "ok")
    return {"estado": estado, "n_errores": n_err, "n_no_leidos": n_nl, "filas": filas, "avisos": avisos,
            "proceso": proceso, "leido": leido}
