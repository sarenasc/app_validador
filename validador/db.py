"""Base de datos SQLite: maestros, procesos (etiqueta esperada) e historial de validaciones."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "validador.db"

# Maestros: tabla -> (título, clave primaria, columnas [(nombre, título)])
MAESTROS = {
    "productor": ("Productores (Grower)", ["csg"], [
        ("csg", "CSG"), ("nombre", "Nombre"), ("region", "Región"), ("provincia", "Provincia"),
        ("comuna", "Comuna"), ("ggn", "GGN")]),
    "sdp": ("Sitios de producción (SDP)", ["csg", "sdp"], [
        ("csg", "CSG"), ("sdp", "SDP"), ("descripcion", "Descripción")]),
    "planta": ("Plantas (Packing)", ["csp"], [
        ("csp", "CSP"), ("nombre", "Nombre"), ("region", "Región"), ("provincia", "Provincia"),
        ("comuna", "Comuna"), ("fda", "FDA"), ("coc", "CoC")]),
    "exportadora": ("Exportadoras", ["cse"], [("cse", "CSE"), ("nombre", "Nombre")]),
    "embalaje": ("Embalajes", ["codigo"], [
        ("codigo", "Código"), ("especie", "Especie"), ("peso_kg", "Peso kg"), ("peso_lb", "Peso lb"),
        ("plu", "PLU")]),
    "especie": ("Especies", ["especie"], [("especie", "Especie"), ("nombre_ingles", "Nombre inglés")]),
    "variedad": ("Variedades", ["especie", "variedad"], [("especie", "Especie"), ("variedad", "Variedad")]),
    "categoria": ("Categorías", ["categoria"], [("categoria", "Categoría")]),
}

# Campos del proceso (etiqueta esperada)
CAMPOS_PROCESO = ["proc", "lote", "fecha", "csg", "sdp", "csp", "cse", "embalaje", "especie",
                  "variedad", "categoria", "plu", "observacion"]


def conectar():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def crear_tablas():
    with conectar() as con:
        for tabla, (_, pk, cols) in MAESTROS.items():
            defs = ", ".join(f"{c} TEXT" for c, _ in cols)
            con.execute(f"CREATE TABLE IF NOT EXISTS {tabla} ({defs}, PRIMARY KEY ({', '.join(pk)}))")
        defs = ", ".join(f"{c} TEXT" for c in CAMPOS_PROCESO)
        con.execute(f"""CREATE TABLE IF NOT EXISTS proceso (
            id INTEGER PRIMARY KEY AUTOINCREMENT, {defs}, activo INTEGER DEFAULT 1,
            creado TEXT, actualizado TEXT, UNIQUE (proc, lote))""")
        con.execute("""CREATE TABLE IF NOT EXISTS validacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fecha_hora TEXT, proceso_id INTEGER,
            proc TEXT, lote TEXT, resultado TEXT, errores INTEGER, no_leidos INTEGER,
            dispositivo TEXT, detalle TEXT)""")


def _limpiar(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


# ---------- maestros ----------
def listar(tabla):
    _, pk, _ = MAESTROS[tabla]
    with conectar() as con:
        return [dict(r) for r in con.execute(f"SELECT * FROM {tabla} ORDER BY {', '.join(pk)}")]


def obtener(tabla, **clave):
    where = " AND ".join(f"{k} = ?" for k in clave)
    with conectar() as con:
        r = con.execute(f"SELECT * FROM {tabla} WHERE {where}", list(clave.values())).fetchone()
        return dict(r) if r else None


def guardar(tabla, fila):
    _, pk, cols = MAESTROS[tabla]
    nombres = [c for c, _ in cols]
    datos = {c: _limpiar(fila.get(c)) for c in nombres}
    if any(not datos[k] for k in pk):
        raise ValueError(f"Falta la clave: {', '.join(pk)}")
    for k in pk:
        datos[k] = datos[k].upper()
    with conectar() as con:
        con.execute(f"INSERT OR REPLACE INTO {tabla} ({', '.join(nombres)}) VALUES ({', '.join('?' * len(nombres))})",
                    [datos[c] for c in nombres])
    return datos


def eliminar(tabla, clave):
    where = " AND ".join(f"{k} = ?" for k in clave)
    with conectar() as con:
        con.execute(f"DELETE FROM {tabla} WHERE {where}", list(clave.values()))


# ---------- procesos ----------
def listar_procesos(solo_activos=False):
    sql = "SELECT * FROM proceso" + (" WHERE activo = 1" if solo_activos else "")
    with conectar() as con:
        return [dict(r) for r in con.execute(sql + " ORDER BY fecha DESC, CAST(proc AS INTEGER) DESC, "
                                                  "CAST(lote AS INTEGER) DESC")]


def obtener_proceso(pid):
    with conectar() as con:
        r = con.execute("SELECT * FROM proceso WHERE id = ?", [pid]).fetchone()
        return dict(r) if r else None


def buscar_proceso(proc, lote):
    """Busca por PROC + LOTE; si no hay, por PROC solo cuando es único."""
    with conectar() as con:
        if proc and lote:
            r = con.execute("SELECT * FROM proceso WHERE proc = ? AND lote = ?", [proc, lote]).fetchone()
            if r:
                return dict(r)
        if proc:
            rs = con.execute("SELECT * FROM proceso WHERE proc = ? AND activo = 1", [proc]).fetchall()
            if len(rs) == 1:
                return dict(rs[0])
    return None


def guardar_proceso(datos, pid=None):
    datos = {c: _limpiar(datos.get(c)) for c in CAMPOS_PROCESO}
    for c in CAMPOS_PROCESO:
        if datos[c] and c != "observacion":
            datos[c] = datos[c].upper()
    if not datos["proc"] or not datos["lote"]:
        raise ValueError("PROC y LOTE son obligatorios")
    ahora = datetime.now().isoformat(timespec="seconds")
    with conectar() as con:
        if pid is None:
            r = con.execute("SELECT id FROM proceso WHERE proc = ? AND lote = ?",
                            [datos["proc"], datos["lote"]]).fetchone()
            pid = r["id"] if r else None
        if pid is None:
            cur = con.execute(
                f"INSERT INTO proceso ({', '.join(CAMPOS_PROCESO)}, activo, creado, actualizado) "
                f"VALUES ({', '.join('?' * len(CAMPOS_PROCESO))}, 1, ?, ?)",
                [datos[c] for c in CAMPOS_PROCESO] + [ahora, ahora])
            pid = cur.lastrowid
        else:
            con.execute(f"UPDATE proceso SET {', '.join(f'{c} = ?' for c in CAMPOS_PROCESO)}, actualizado = ? "
                        "WHERE id = ?", [datos[c] for c in CAMPOS_PROCESO] + [ahora, pid])
    return obtener_proceso(pid)


def activar_proceso(pid, activo):
    with conectar() as con:
        con.execute("UPDATE proceso SET activo = ? WHERE id = ?", [1 if activo else 0, pid])


def eliminar_proceso(pid):
    with conectar() as con:
        con.execute("DELETE FROM proceso WHERE id = ?", [pid])


# ---------- historial ----------
def registrar_validacion(resultado, dispositivo=None):
    p = resultado.get("proceso") or {}
    with conectar() as con:
        cur = con.execute(
            "INSERT INTO validacion (fecha_hora, proceso_id, proc, lote, resultado, errores, no_leidos, "
            "dispositivo, detalle) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [datetime.now().isoformat(timespec="seconds"), p.get("id"),
             resultado["leido"].get("proc"), resultado["leido"].get("lote"), resultado["estado"],
             resultado["n_errores"], resultado["n_no_leidos"], dispositivo,
             json.dumps(resultado, ensure_ascii=False)])
        return cur.lastrowid


def listar_validaciones(limite=200):
    with conectar() as con:
        rs = con.execute("SELECT * FROM validacion ORDER BY id DESC LIMIT ?", [limite]).fetchall()
    out = []
    for r in rs:
        d = dict(r)
        d["detalle"] = json.loads(d["detalle"] or "{}")
        out.append(d)
    return out
