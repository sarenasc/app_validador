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
        # letras/dígitos que el OCR confunde (O/0, S/5, I/1, B/8...)
        return a.translate(_OCR_DIGITOS) == b.translate(_OCR_DIGITOS), "lectura aproximada (O/0, S/5...)"
    a, b = norm_texto(leido), norm_texto(esperado)
    if a == b or (b and b in a and len(a) - len(b) <= 3):
        return True, None
    if len(b) >= 6 and _distancia(a, b) <= 1:
        return True, "lectura aproximada"
    return False, None


def _peso_lb(peso_kg):
    p = norm_peso(peso_kg)
    return None if p is None else round(p * 2.20462, 2)


# Grupos de la etiqueta: cada uno se valida contra su propio maestro (o contra el proceso)
GRUPOS = {
    "productor": ("Productor", ["csg", "prod_region", "prod_provincia", "prod_comuna", "ggn", "sdp"]),
    "planta": ("Planta", ["csp", "planta_region", "planta_provincia", "planta_comuna", "fda", "coc"]),
    "exportadora": ("Exportadora", ["cse", "exportadora"]),
    "proceso": ("Proceso", ["proc", "lote", "fecha", "especie", "variedad", "categoria", "embalaje", "peso_kg",
                            "peso_lb", "plu"]),
}


def identificar(tabla, col, leido_val, texto, obtener=db.obtener, listar=db.listar):
    """Clave del maestro según la etiqueta: la leída si existe en la base; si no, la única que aparezca en el texto."""
    es_codigo = tabla == "embalaje"
    if leido_val:
        k = norm_texto(leido_val) if es_codigo else norm_num(leido_val)
        if k and obtener(tabla, **{col: k}):
            return k, "leido"
    if texto:
        T = norm_texto(texto)
        tn = t0 = T.translate(_OCR_DIGITOS)
        hall = []
        for f in listar(tabla):
            v = str(f.get(col) or "")
            if es_codigo and len(v) >= 5 and norm_texto(v).translate(_OCR_DIGITOS) in t0:
                hall.append(v)
            elif not es_codigo and len(norm_num(v)) >= 5 and norm_num(v) in tn:
                hall.append(v)
        if len(hall) == 1:
            return hall[0], "texto"
    return None, None


def esperados(proceso, leido, obtener=db.obtener, texto=None, listar=db.listar):
    """Arma campo -> (valor esperado, origen).

    Productor, planta, exportadora y embalaje se buscan en la base por la clave IMPRESA en la etiqueta
    (o la que aparece en el texto); el proceso aporta los datos propios del proceso.
    Devuelve (esp, claves) con las claves de maestro identificadas.
    """
    base = proceso or {}
    esp = {}
    for c in ("proc", "lote", "fecha", "csg", "sdp", "csp", "cse", "embalaje", "especie", "variedad",
              "categoria", "plu"):
        if base.get(c):
            esp[c] = (base[c], "proceso")

    claves = {}
    for campo, tabla, col in (("csg", "productor", "csg"), ("csp", "planta", "csp"), ("cse", "exportadora", "cse"),
                              ("embalaje", "embalaje", "codigo")):
        k, _ = identificar(tabla, col, leido.get(campo), texto, obtener, listar)
        claves[campo] = k
        if k and campo not in esp:
            esp[campo] = (k, f"maestro {tabla}")
        if not k and leido.get(campo):
            claves[campo + "_no_existe"] = norm_texto(leido[campo]) if campo == "embalaje" else norm_num(leido[campo])
        if not k and base.get(campo):  # no se identificó en la etiqueta: se usa la del proceso
            claves[campo] = base[campo]

    if claves["csg"] and (p := obtener("productor", csg=str(claves["csg"]).upper())):
        for c, m in (("prod_region", "region"), ("prod_provincia", "provincia"),
                     ("prod_comuna", "comuna"), ("ggn", "ggn")):
            if p.get(m):
                esp[c] = (p[m], f"maestro productor {claves['csg']}")
    if claves["csp"] and (p := obtener("planta", csp=str(claves["csp"]).upper())):
        for c, m in (("planta_region", "region"), ("planta_provincia", "provincia"),
                     ("planta_comuna", "comuna"), ("fda", "fda"), ("coc", "coc")):
            if p.get(m):
                esp[c] = (p[m], f"maestro planta {claves['csp']}")
    if claves["cse"] and (e := obtener("exportadora", cse=str(claves["cse"]).upper())):
        if e.get("nombre"):
            esp["exportadora"] = (e["nombre"], f"maestro exportadora {claves['cse']}")
    if claves["embalaje"] and (e := obtener("embalaje", codigo=norm_texto(claves["embalaje"]))):
        if e.get("peso_kg"):
            esp["peso_kg"] = (e["peso_kg"], "maestro embalaje")
            esp["peso_lb"] = (e.get("peso_lb") or _peso_lb(e["peso_kg"]), "maestro embalaje")
        if e.get("plu") and "plu" not in esp:
            esp["plu"] = (e["plu"], "maestro embalaje")
    return esp, claves


CAMPOS_IDENTIFICAN = ("proc", "lote", "csg", "sdp", "csp", "cse", "embalaje", "variedad", "fecha", "categoria", "plu")


def mejor_proceso(leido, procesos, texto=None):
    """Busca entre los procesos de la base el que más coincide con lo leído.

    Devuelve (proceso, texto con los campos coincidentes) o (None, None) si no hay uno claro:
    se exigen al menos 3 coincidencias y que no haya empate con otro proceso.
    """
    puntajes = []
    for p in procesos:
        iguales = [c for c in CAMPOS_IDENTIFICAN if p.get(c) and (
            (leido.get(c) and comparar(CAMPOS[c][1], leido[c], p[c])[0])
            or (texto and buscar_en_texto(c, CAMPOS[c][1], p[c], texto) == "exacto"))]
        puntajes.append((len(iguales), iguales, p))
    puntajes.sort(key=lambda x: -x[0])
    if not puntajes or puntajes[0][0] < 3 or (len(puntajes) > 1 and puntajes[1][0] == puntajes[0][0]):
        return None, None
    n, iguales, p = puntajes[0]
    return p, ", ".join(CAMPOS[c][0] for c in iguales)


def _dist_subcadena(patron, texto):
    """Mínima distancia de edición entre `patron` y cualquier subcadena de `texto`."""
    prev = [0] * (len(texto) + 1)
    for i, pc in enumerate(patron, 1):
        cur = [i] + [0] * len(texto)
        for j, tc in enumerate(texto, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (pc != tc))
        prev = cur
    return min(prev)


# Campos numéricos cortos: solo se buscan junto a su rótulo impreso (ej. "LOTE: 47")
_ROTULO = {"proc": r"PR[O0]C", "lote": r"L[O0]TE", "plu": r"PLU", "cse": r"[CE][S5]E", "sdp": r"[S5]DP"}
_N = "[0-9OQDILSB|]"


def buscar_en_texto(campo, tipo, esperado, texto, alias=None):
    """Busca el valor esperado (de la base) dentro del texto OCR. Devuelve 'exacto', 'parecido' o None."""
    T = norm_texto(texto)
    if not T or not esperado:
        return None
    if tipo == "num":
        v = norm_num(esperado)
        if campo in _ROTULO or len(v) < 5:
            rot = _ROTULO.get(campo)
            if not rot:
                return None
            # el OCR puede pegar letras del rótulo siguiente ("89366SDP"): se prueban los prefijos de lo leído
            crudos = re.findall(rot + f"({_N}{{1,{len(v) + 2}}})", T)
            prefijos = {norm_num(m[:i]) for m in crudos for i in range(1, len(m) + 1)}
            if v in prefijos:
                return "exacto"
            return "parecido" if len(v) >= 4 and any(len(x) == len(v) and _distancia(x, v) == 1
                                                      for x in prefijos) else None
        tn = T.translate(_OCR_DIGITOS)
        if v in tn:
            return "exacto"
        return "parecido" if len(v) >= 6 and _dist_subcadena(v, tn) <= 1 else None
    if tipo == "fecha":
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", str(esperado))
        if not m:
            return None
        y, mo, d = m.group(1)[2:], m.group(2), m.group(3)
        tn = T.translate(_OCR_DIGITOS)
        variantes = (mo + d + y, d + mo + y, y + mo + d)
        if any(x in tn for x in variantes):
            return "exacto"
        return "parecido" if any(_dist_subcadena(x, tn) <= 1 for x in variantes) else None
    if tipo == "peso":
        v = norm_texto(str(norm_peso(esperado)).rstrip("0").rstrip("."))
        suf = r"K[G6]" if campo == "peso_kg" else r"[LI1|]B"
        return "exacto" if re.search(v + suf, T) else None
    if tipo == "codigo":
        v, tc = norm_texto(esperado).translate(_OCR_DIGITOS), T.translate(_OCR_DIGITOS)
        if v in tc:
            return "exacto"
        return "parecido" if len(v) >= 6 and _dist_subcadena(v, tc) <= 1 else None
    if tipo == "region":
        # un dígito suelto no es confiable: se busca junto a la provincia (ej. "6 /CACHAPOAL")
        if not alias:
            return None
        v = norm_region(esperado) + norm_texto(alias[0])
        return "exacto" if v in T or _dist_subcadena(v, T) <= 1 else None
    for v in [esperado] + list(alias or []):
        v = norm_texto(v)
        if len(v) < 4:
            continue
        if v in T:
            return "exacto"
        tolerancia = 2 if len(v) >= 12 else (1 if len(v) >= 6 else 0)
        if tolerancia and _dist_subcadena(v, T) <= tolerancia:
            return "exacto"
    return None


def validar(leido, proceso=None, obtener=db.obtener, texto=None, listar=db.listar):
    leido = {k: (str(v).strip() if v not in (None, "") else "") for k, v in (leido or {}).items()}
    esp, claves = esperados(proceso, leido, obtener, texto, listar)
    filas, avisos = [], []
    alias_especie = []
    if texto and esp.get("especie"):
        e = obtener("especie", especie=str(esp["especie"][0]).upper())
        alias_especie = [e["nombre_ingles"]] if e and e.get("nombre_ingles") else []
    alias_campo = {"especie": alias_especie}
    for reg, prov in (("prod_region", "prod_provincia"), ("planta_region", "planta_provincia")):
        if esp.get(prov):
            alias_campo[reg] = [esp[prov][0]]

    if proceso is None:
        avisos.append("No hay un proceso registrado para PROC "
                      f"{leido.get('proc') or '?'} / LOTE {leido.get('lote') or '?'}: "
                      "se validan productor, planta y exportadora contra los maestros.")

    for campo, (titulo, tipo) in CAMPOS.items():
        valor = leido.get(campo, "")
        esperado, origen = esp.get(campo, (None, None))
        fila = {"campo": campo, "titulo": titulo, "leido": valor, "esperado": esperado, "origen": origen,
                "nota": None}
        if tipo == "info":
            fila["estado"] = "info"
        elif esperado in (None, ""):
            fila["estado"] = "sin_referencia"
        else:
            ok, nota = comparar(tipo, valor, esperado) if valor else (False, None)
            # Si el campo no se separó bien, se busca el valor de la base directamente en el texto leído
            en_texto = None if ok or not texto else buscar_en_texto(campo, tipo, esperado, texto,
                                                                     alias_campo.get(campo))
            if ok:
                fila["estado"], fila["nota"] = "ok", nota
            elif en_texto == "exacto":
                fila["estado"], fila["nota"] = "ok", "encontrado en el texto leído"
            elif en_texto == "parecido":
                fila["estado"], fila["nota"] = "dudoso", "se lee parecido pero no igual: revisa la etiqueta"
            else:
                fila["estado"] = "error" if valor else "no_leido"
        filas.append(fila)

    # Consistencia con maestros: claves que no existen y relaciones
    err_grupo = {g: [] for g in GRUPOS}
    for campo, grupo, nombre in (("csg", "productor", "productores"), ("csp", "planta", "plantas"),
                                 ("cse", "exportadora", "exportadoras"), ("embalaje", "proceso", "embalajes")):
        if claves.get(campo + "_no_existe") and not claves.get(campo):
            err_grupo[grupo].append(f"El {CAMPOS[campo][0].split()[0]} {claves[campo + '_no_existe']} "
                                    f"no existe en el maestro de {nombre}.")
    especie = (proceso or {}).get("especie") or leido.get("especie")
    variedad = leido.get("variedad")
    if especie and variedad and obtener("variedad", especie=especie.upper(), variedad=variedad.upper()) is None:
        err_grupo["proceso"].append(f"La variedad {variedad} no está registrada para {especie}.")
    sdp = norm_num(leido.get("sdp"))
    if claves.get("csg") and sdp and obtener("sdp", csg=str(claves["csg"]), sdp=sdp) is None:
        err_grupo["productor"].append(f"El SDP {sdp} no está registrado para el productor CSG {claves['csg']}.")

    grupos = {}
    por_campo = {f["campo"]: f for f in filas}
    for g, (titulo, campos) in GRUPOS.items():
        fs = [por_campo[c] for c in campos]
        n_e = sum(f["estado"] == "error" for f in fs) + len(err_grupo[g])
        n_d = sum(f["estado"] in ("no_leido", "dudoso") for f in fs)
        validados = sum(f["estado"] not in ("sin_referencia", "info") for f in fs)
        clave = {"productor": claves.get("csg"), "planta": claves.get("csp"), "exportadora": claves.get("cse"),
                 "proceso": (f"PROC {proceso['proc']} / LOTE {proceso['lote']}" if proceso else None)}[g]
        estado = "error" if n_e else "revisar" if n_d else "ok" if validados else "sin_datos"
        if g == "proceso" and not proceso and not n_e:
            estado = "sin_proceso"
        grupos[g] = {"titulo": titulo, "clave": clave, "estado": estado, "errores": n_e, "revisar": n_d,
                     "mensajes": err_grupo[g]}
        avisos.extend(err_grupo[g])

    n_err = sum(x["errores"] for x in grupos.values())
    n_nl = sum(f["estado"] in ("no_leido", "dudoso") for f in filas)
    estado = "error" if n_err else ("revisar" if n_nl else "ok")
    return {"estado": estado, "n_errores": n_err, "n_no_leidos": n_nl, "filas": filas, "avisos": avisos,
            "grupos": grupos, "proceso": proceso, "leido": leido}
