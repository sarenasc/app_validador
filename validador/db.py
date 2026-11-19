"""Base de datos: maestros, procesos (etiqueta esperada) e historial de validaciones.

Producción: SQL Server (vía pyodbc). La conexión se configura la primera vez desde la web (se guarda en
data/config.json) o con variables de entorno DB_SERVER, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD (Docker).
Los tests usan SQLite en memoria de disco temporal con `usar_sqlite(ruta)`.
"""

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PATH = RAIZ / "data" / "config.json"

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

_estado = {"motor": None, "cfg": None, "sqlite": None}


def q(nombre):
    """Identificador entre comillas (PROC es palabra reservada en SQL Server)."""
    return f'"{nombre}"'


# ---------------- configuración de la conexión ----------------
def _driver_odbc():
    import pyodbc
    for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"):
        if d in pyodbc.drivers():
            return d
    raise RuntimeError("No hay driver ODBC de SQL Server instalado (ODBC Driver 17 o 18).")


def config_desde_entorno():
    if not os.environ.get("DB_SERVER"):
        return None
    return {"servidor": os.environ["DB_SERVER"], "puerto": os.environ.get("DB_PORT", "1433"),
            "base": os.environ.get("DB_NAME", "validador_etiquetas"), "usuario": os.environ.get("DB_USER", ""),
            "clave": os.environ.get("DB_PASSWORD", ""), "windows": os.environ.get("DB_WINDOWS_AUTH") == "1",
            "confiar_certificado": os.environ.get("DB_TRUST_CERT", "1") == "1"}


def leer_config():
    cfg = config_desde_entorno()
    if cfg:
        return cfg
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return None


def validar_config(cfg):
    cfg = {k: (v.strip() if isinstance(v, str) else v) for k, v in (cfg or {}).items()}
    if not cfg.get("servidor"):
        raise ValueError("Falta el servidor")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,100}", cfg.get("base") or ""):
        raise ValueError("Nombre de base inválido: solo letras, números y _")
    if not cfg.get("windows") and not cfg.get("usuario"):
        raise ValueError("Falta el usuario (o marca autenticación de Windows)")
    if str(cfg.get("puerto") or "").strip() and not str(cfg["puerto"]).isdigit():
        raise ValueError("El puerto debe ser un número")
    return cfg


def _cadena(cfg, base=None):
    servidor = cfg["servidor"]
    if cfg.get("puerto") and "\\" not in servidor:  # con instancia con nombre no se pone puerto
        servidor = f"{servidor},{cfg['puerto']}"
    partes = [f"DRIVER={{{_driver_odbc()}}}", f"SERVER={servidor}", f"DATABASE={base or cfg['base']}",
              "Encrypt=yes", f"TrustServerCertificate={'yes' if cfg.get('confiar_certificado', True) else 'no'}"]
    if cfg.get("windows"):
        partes.append("Trusted_Connection=yes")
    else:
        partes += [f"UID={cfg['usuario']}", "PWD={" + str(cfg.get("clave", "")).replace("}", "}}") + "}"]
    return ";".join(partes)


def probar_conexion(cfg):
    """Conecta a master con los datos dados. Devuelve (ok, mensaje)."""
    import pyodbc
    try:
        cfg = validar_config(cfg)
        con = pyodbc.connect(_cadena(cfg, "master"), timeout=8, autocommit=True)
        version = con.cursor().execute("SELECT @@VERSION").fetchone()[0].split("\n")[0]
        existe = con.cursor().execute("SELECT DB_ID(?)", cfg["base"]).fetchone()[0] is not None
        con.close()
        return True, f"Conectado a {version.strip()}. La base '{cfg['base']}' " + (
            "ya existe (se usarán/crearán sus tablas)." if existe else "no existe: se creará.")
    except Exception as e:  # noqa: BLE001 - se muestra el error de conexión al usuario
        return False, str(e)


def inicializar_sqlserver(cfg, guardar=True):
    """Crea la base (si no existe) y las tablas, guarda la configuración y deja la app usando SQL Server."""
    import pyodbc
    cfg = validar_config(cfg)
    con = pyodbc.connect(_cadena(cfg, "master"), timeout=8, autocommit=True)
    if con.cursor().execute("SELECT DB_ID(?)", cfg["base"]).fetchone()[0] is None:
        con.cursor().execute(f"CREATE DATABASE [{cfg['base']}]")
    con.close()
    _estado.update(motor="mssql", cfg=cfg)
    crear_tablas()
    if guardar and not config_desde_entorno():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def iniciar():
    """Al arrancar: si hay configuración, conecta y asegura las tablas. Devuelve True si quedó configurada."""
    cfg = leer_config()
    if not cfg:
        return False
    inicializar_sqlserver(cfg, guardar=False)
    return True


def configurada():
    return _estado["motor"] is not None


def usar_sqlite(ruta):
    """Solo para tests."""
    _estado.update(motor="sqlite", sqlite=Path(ruta), cfg=None)
    crear_tablas()


@contextmanager
def conectar():
    motor = _estado["motor"]
    if motor is None:
        raise RuntimeError("La base de datos no está configurada")
    if motor == "sqlite":
        con = sqlite3.connect(_estado["sqlite"])
    else:
        import pyodbc
        con = pyodbc.connect(_cadena(_estado["cfg"]), timeout=10)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _filas(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _una(cur):
    f = _filas(cur)
    return f[0] if f else None


def crear_tablas():
    mssql = _estado["motor"] == "mssql"
    texto = "NVARCHAR(400)" if mssql else "TEXT"
    clave = "NVARCHAR(100) NOT NULL" if mssql else "TEXT NOT NULL"
    corto = "NVARCHAR(50)" if mssql else "TEXT"
    largo = "NVARCHAR(MAX)" if mssql else "TEXT"
    autoinc = "INT IDENTITY(1,1) PRIMARY KEY" if mssql else "INTEGER PRIMARY KEY AUTOINCREMENT"

    def si_no_existe(con, tabla, ddl):
        if mssql:
            con.cursor().execute(f"IF OBJECT_ID(N'dbo.{tabla}', N'U') IS NULL CREATE TABLE dbo.{q(tabla)} ({ddl})")
        else:
            con.cursor().execute(f"CREATE TABLE IF NOT EXISTS {q(tabla)} ({ddl})")

    with conectar() as con:
        for tabla, (_, pk, cols) in MAESTROS.items():
            defs = ", ".join(f"{q(c)} {clave if c in pk else texto}" for c, _ in cols)
            si_no_existe(con, tabla, f"{defs}, PRIMARY KEY ({', '.join(q(c) for c in pk)})")
        defs = ", ".join(f"{q(c)} {(clave if c in ('proc', 'lote') else (largo if c == 'observacion' else corto))}"
                         for c in CAMPOS_PROCESO)
        si_no_existe(con, "proceso", f"{q('id')} {autoinc}, {defs}, {q('activo')} INT DEFAULT 1, "
                                     f"{q('creado')} {corto}, {q('actualizado')} {corto}, "
                                     f"UNIQUE ({q('proc')}, {q('lote')})")
        si_no_existe(con, "validacion", f"{q('id')} {autoinc}, {q('fecha_hora')} {corto}, {q('proceso_id')} INT, "
                                        f"{q('proc')} {corto}, {q('lote')} {corto}, {q('resultado')} {corto}, "
                                        f"{q('errores')} INT, {q('no_leidos')} INT, {q('dispositivo')} {texto}, "
                                        f"{q('detalle')} {largo}")


def _limpiar(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _insertar_id(con, sql, valores):
    """INSERT que devuelve el id generado (IDENTITY / AUTOINCREMENT)."""
    cur = con.cursor()
    if _estado["motor"] == "mssql":
        cur.execute(sql + "; SELECT CAST(SCOPE_IDENTITY() AS INT)", valores)
        cur.nextset()
        return cur.fetchone()[0]
    cur.execute(sql, valores)
    return cur.lastrowid


# ---------------- maestros ----------------
def listar(tabla):
    _, pk, _ = MAESTROS[tabla]
    with conectar() as con:
        return _filas(con.cursor().execute(f"SELECT * FROM {q(tabla)} ORDER BY {', '.join(q(c) for c in pk)}"))


def obtener(tabla, **clave):
    where = " AND ".join(f"{q(k)} = ?" for k in clave)
    with conectar() as con:
        return _una(con.cursor().execute(f"SELECT * FROM {q(tabla)} WHERE {where}", list(clave.values())))


def guardar(tabla, fila):
    _, pk, cols = MAESTROS[tabla]
    nombres = [c for c, _ in cols]
    datos = {c: _limpiar(fila.get(c)) for c in nombres}
    if any(not datos[k] for k in pk):
        raise ValueError(f"Falta la clave: {', '.join(pk)}")
    for k in pk:
        datos[k] = datos[k].upper()
    otros = [c for c in nombres if c not in pk]
    with conectar() as con:
        cur = con.cursor()
        n = 0
        if otros:
            cur.execute(f"UPDATE {q(tabla)} SET {', '.join(f'{q(c)} = ?' for c in otros)} "
                        f"WHERE {' AND '.join(f'{q(k)} = ?' for k in pk)}",
                        [datos[c] for c in otros] + [datos[k] for k in pk])
            n = cur.rowcount
        else:
            n = len(_filas(cur.execute(f"SELECT 1 AS x FROM {q(tabla)} WHERE "
                                       f"{' AND '.join(f'{q(k)} = ?' for k in pk)}", [datos[k] for k in pk])))
        if not n:
            cur.execute(f"INSERT INTO {q(tabla)} ({', '.join(q(c) for c in nombres)}) "
                        f"VALUES ({', '.join('?' * len(nombres))})", [datos[c] for c in nombres])
    return datos


def eliminar(tabla, clave):
    where = " AND ".join(f"{q(k)} = ?" for k in clave)
    with conectar() as con:
        con.cursor().execute(f"DELETE FROM {q(tabla)} WHERE {where}", list(clave.values()))


# ---------------- procesos ----------------
def listar_procesos(solo_activos=False):
    num = "TRY_CAST({} AS INT)" if _estado["motor"] == "mssql" else "CAST({} AS INTEGER)"
    sql = (f"SELECT * FROM {q('proceso')}" + (f" WHERE {q('activo')} = 1" if solo_activos else "")
           + f" ORDER BY {q('fecha')} DESC, {num.format(q('proc'))} DESC, {num.format(q('lote'))} DESC")
    with conectar() as con:
        return _filas(con.cursor().execute(sql))


def obtener_proceso(pid):
    with conectar() as con:
        return _una(con.cursor().execute(f"SELECT * FROM {q('proceso')} WHERE {q('id')} = ?", [pid]))


def buscar_proceso(proc, lote):
    """Busca por PROC + LOTE; si no hay, por PROC solo cuando es único."""
    with conectar() as con:
        cur = con.cursor()
        if proc and lote:
            r = _una(cur.execute(f"SELECT * FROM {q('proceso')} WHERE {q('proc')} = ? AND {q('lote')} = ?",
                                 [proc, lote]))
            if r:
                return r
        if proc:
            rs = _filas(cur.execute(f"SELECT * FROM {q('proceso')} WHERE {q('proc')} = ? AND {q('activo')} = 1",
                                    [proc]))
            if len(rs) == 1:
                return rs[0]
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
        cur = con.cursor()
        if pid is None:
            r = _una(cur.execute(f"SELECT {q('id')} AS id FROM {q('proceso')} WHERE {q('proc')} = ? AND {q('lote')} = ?",
                                 [datos["proc"], datos["lote"]]))
            pid = r["id"] if r else None
        if pid is None:
            pid = _insertar_id(
                con, f"INSERT INTO {q('proceso')} ({', '.join(q(c) for c in CAMPOS_PROCESO)}, {q('activo')}, "
                     f"{q('creado')}, {q('actualizado')}) VALUES ({', '.join('?' * len(CAMPOS_PROCESO))}, 1, ?, ?)",
                [datos[c] for c in CAMPOS_PROCESO] + [ahora, ahora])
        else:
            cur.execute(f"UPDATE {q('proceso')} SET {', '.join(f'{q(c)} = ?' for c in CAMPOS_PROCESO)}, "
                        f"{q('actualizado')} = ? WHERE {q('id')} = ?", [datos[c] for c in CAMPOS_PROCESO] + [ahora, pid])
    return obtener_proceso(pid)


def activar_proceso(pid, activo):
    with conectar() as con:
        con.cursor().execute(f"UPDATE {q('proceso')} SET {q('activo')} = ? WHERE {q('id')} = ?",
                             [1 if activo else 0, pid])


def eliminar_proceso(pid):
    with conectar() as con:
        con.cursor().execute(f"DELETE FROM {q('proceso')} WHERE {q('id')} = ?", [pid])


# ---------------- historial ----------------
def registrar_validacion(resultado, dispositivo=None):
    p = resultado.get("proceso") or {}
    with conectar() as con:
        return _insertar_id(
            con, f"INSERT INTO {q('validacion')} ({q('fecha_hora')}, {q('proceso_id')}, {q('proc')}, {q('lote')}, "
                 f"{q('resultado')}, {q('errores')}, {q('no_leidos')}, {q('dispositivo')}, {q('detalle')}) "
                 f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [datetime.now().isoformat(timespec="seconds"), p.get("id"),
             resultado["leido"].get("proc"), resultado["leido"].get("lote"), resultado["estado"],
             resultado["n_errores"], resultado["n_no_leidos"], dispositivo,
             json.dumps(resultado, ensure_ascii=False, default=str)])


def listar_validaciones(limite=200):
    limite = max(1, min(int(limite), 1000))
    if _estado["motor"] == "mssql":
        sql = f"SELECT TOP ({limite}) * FROM {q('validacion')} ORDER BY {q('id')} DESC"
    else:
        sql = f"SELECT * FROM {q('validacion')} ORDER BY {q('id')} DESC LIMIT {limite}"
    with conectar() as con:
        rs = _filas(con.cursor().execute(sql))
    for d in rs:
        d["detalle"] = json.loads(d["detalle"] or "{}")
    return rs
