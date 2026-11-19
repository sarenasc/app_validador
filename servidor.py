"""Validador de Etiquetas – API (FastAPI) + interfaz web para celular/tablet.

Ejecutar:  python servidor.py          (solo este PC: http://localhost:8520)
           python servidor.py --red    (accesible desde celulares de la red: http://<IP-del-PC>:8520)
"""

import socket
import sys
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from validador import datos_ejemplo, db
from validador.validacion import norm_num, norm_texto, validar

RAIZ = Path(__file__).parent
WEB = RAIZ / "web"
PUERTO = 8520


@asynccontextmanager
async def ciclo(app):
    db.crear_tablas()
    datos_ejemplo.cargar_si_vacia()
    yield


app = FastAPI(title="Validador de Etiquetas", lifespan=ciclo)


def _tabla(tabla):
    if tabla not in db.MAESTROS:
        raise HTTPException(404, f"Maestro desconocido: {tabla}")
    return tabla


# ---------------- maestros ----------------
@app.get("/api/maestros")
def maestros():
    return {t: {"titulo": tit, "clave": pk, "columnas": [{"campo": c, "titulo": n} for c, n in cols],
                "filas": db.listar(t)}
            for t, (tit, pk, cols) in db.MAESTROS.items()}


@app.post("/api/maestros/{tabla}")
def guardar_maestro(tabla: str, fila: dict = Body(...)):
    try:
        return db.guardar(_tabla(tabla), fila)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/maestros/{tabla}/eliminar")
def eliminar_maestro(tabla: str, clave: dict = Body(...)):
    _, pk, _ = db.MAESTROS[_tabla(tabla)]
    db.eliminar(tabla, {k: clave.get(k) for k in pk})
    return {"ok": True}


# ---------------- procesos ----------------
# (maestro, clave del maestro -> campo del formulario, columnas -> campo del formulario)
SINCRONIZAR = [
    ("productor", {"csg": "csg"}, {"region": "prod_region", "provincia": "prod_provincia",
                                   "comuna": "prod_comuna", "ggn": "ggn"}),
    ("planta", {"csp": "csp"}, {"region": "planta_region", "provincia": "planta_provincia",
                                "comuna": "planta_comuna", "fda": "fda", "coc": "coc"}),
    ("exportadora", {"cse": "cse"}, {"nombre": "exportadora"}),
    ("embalaje", {"codigo": "embalaje"}, {"especie": "especie", "peso_kg": "peso_kg", "peso_lb": "peso_lb",
                                          "plu": "plu"}),
    ("especie", {"especie": "especie"}, {}),
    ("variedad", {"especie": "especie", "variedad": "variedad"}, {}),
    ("sdp", {"csg": "csg", "sdp": "sdp"}, {}),
    ("categoria", {"categoria": "categoria"}, {}),
]


def _sincronizar_maestros(form, actualizar):
    """Crea maestros faltantes; informa (y opcionalmente actualiza) diferencias con los existentes."""
    creados, diferencias = [], []
    for tabla, claves, cols in SINCRONIZAR:
        clave = {k: str(form.get(f) or "").strip().upper() for k, f in claves.items()}
        if not all(clave.values()):
            continue
        actual = db.obtener(tabla, **clave)
        nuevos = {k: str(form.get(f)).strip() for k, f in cols.items() if str(form.get(f) or "").strip()}
        if actual is None:
            db.guardar(tabla, {**clave, **nuevos})
            creados.append(f"{db.MAESTROS[tabla][0]}: {' / '.join(clave.values())}")
            continue
        difs = [{"tabla": tabla, "clave": " / ".join(clave.values()), "campo": k, "actual": actual.get(k),
                 "formulario": v}
                for k, v in nuevos.items() if actual.get(k) and norm_texto(actual[k]) != norm_texto(v)]
        faltantes = {k: v for k, v in nuevos.items() if not actual.get(k)}
        if difs and actualizar:
            db.guardar(tabla, {**actual, **nuevos})
        elif faltantes:
            db.guardar(tabla, {**actual, **faltantes})
        if not actualizar:
            diferencias.extend(difs)
    return creados, diferencias


@app.get("/api/procesos")
def procesos(activos: int = 0):
    return db.listar_procesos(bool(activos))


@app.post("/api/procesos")
def guardar_proceso(payload: dict = Body(...)):
    form = payload.get("datos") or {}
    for c in ("proc", "lote", "csg", "csp", "cse", "sdp", "plu"):
        if form.get(c):
            form[c] = norm_num(form[c])
    if form.get("embalaje"):
        form["embalaje"] = norm_texto(form["embalaje"])
    try:
        proceso = db.guardar_proceso(form, payload.get("id"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    creados, diferencias = _sincronizar_maestros(form, bool(payload.get("actualizar_maestros")))
    return {"proceso": proceso, "maestros_creados": creados, "diferencias_maestros": diferencias}


@app.post("/api/procesos/{pid}/activo")
def activar(pid: int, body: dict = Body(...)):
    db.activar_proceso(pid, body.get("activo", True))
    return {"ok": True}


@app.delete("/api/procesos/{pid}")
def eliminar_proceso(pid: int):
    db.eliminar_proceso(pid)
    return {"ok": True}


@app.get("/api/procesos/{pid}/esperado")
def esperado(pid: int):
    """Proceso + datos de maestros, para precargar el formulario."""
    p = db.obtener_proceso(pid)
    if not p:
        raise HTTPException(404, "Proceso no encontrado")
    from validador.validacion import esperados
    return {**p, **{k: v for k, (v, _) in esperados(p, {}).items()}}


# ---------------- validación ----------------
@app.post("/api/validar")
def validar_etiqueta(request: Request, payload: dict = Body(...)):
    leido = payload.get("leido") or {}
    pid = payload.get("proceso_id")
    if pid:
        proceso = db.obtener_proceso(int(pid))
    else:
        proceso = db.buscar_proceso(norm_num(leido.get("proc")), norm_num(leido.get("lote")))
    resultado = validar(leido, proceso)
    if payload.get("guardar", True):
        disp = request.headers.get("user-agent", "")[:120]
        resultado["id_historial"] = db.registrar_validacion(resultado, disp)
    return resultado


@app.get("/api/historial")
def historial(limite: int = 200):
    return db.listar_validaciones(limite)


@app.get("/")
def inicio():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")


def _ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    import uvicorn

    red = "--red" in sys.argv
    host = "0.0.0.0" if red else "127.0.0.1"
    print(f"Validador de Etiquetas en http://localhost:{PUERTO}")
    if red:
        print(f"Desde celulares/tablets de la red: http://{_ip_local()}:{PUERTO}")
    else:
        webbrowser.open(f"http://localhost:{PUERTO}")
    uvicorn.run(app, host=host, port=PUERTO)
