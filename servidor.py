"""Validador de Etiquetas – API (FastAPI) + interfaz web para celular/tablet.

Ejecutar:  python servidor.py          (solo este PC: http://localhost:8520)
           python servidor.py --red    (accesible desde celulares de la red: http://<IP-del-PC>:8520)
"""

import base64
import json
import os
import socket
import sys
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from validador import db
from validador.validacion import mejor_proceso, norm_num, norm_texto, validar

RAIZ = Path(__file__).parent
WEB = RAIZ / "web"
ETIQUETAS = RAIZ / "etiquetas_leidas"  # fotos leídas con su texto OCR y resultado (para revisar lecturas)
PUERTO = int(os.environ.get("PUERTO", "8520"))
ERROR_INICIO = {"mensaje": None}


@asynccontextmanager
async def ciclo(app):
    # Si ya hay conexión configurada (archivo o variables de entorno) se conecta y asegura las tablas;
    # si no, la web muestra el asistente de configuración.
    try:
        db.iniciar()
    except Exception as e:  # noqa: BLE001 - la app debe levantar igual para mostrar el error en la web
        ERROR_INICIO["mensaje"] = f"No se pudo conectar a SQL Server con la configuración guardada: {e}"
    yield


app = FastAPI(title="Validador de Etiquetas", lifespan=ciclo)


@app.middleware("http")
async def exigir_configuracion(request: Request, call_next):
    ruta = request.url.path
    if ruta.startswith("/api/") and not ruta.startswith("/api/config") and not db.configurada():
        return JSONResponse({"detail": "sin_configurar"}, status_code=503)
    return await call_next(request)


# ---------------- configuración inicial (conexión a SQL Server) ----------------
@app.get("/api/config/estado")
def estado_config():
    cfg = db.leer_config() or {}
    return {"configurado": db.configurada(), "error": ERROR_INICIO["mensaje"],
            "desde_entorno": db.config_desde_entorno() is not None,
            "servidor": cfg.get("servidor"), "base": cfg.get("base")}


def _solo_sin_configurar():
    # Una vez configurada, la conexión no se cambia desde la web (borrar data/config.json para rehacerla)
    if db.configurada():
        raise HTTPException(403, "La conexión ya está configurada")


@app.post("/api/config/probar")
def probar_config(cfg: dict = Body(...)):
    _solo_sin_configurar()
    ok, msg = db.probar_conexion(cfg)
    return {"ok": ok, "mensaje": msg}


@app.post("/api/config")
def guardar_config(cfg: dict = Body(...)):
    _solo_sin_configurar()
    try:
        db.inicializar_sqlserver(cfg)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"No se pudo crear la base: {e}")
    ERROR_INICIO["mensaje"] = None
    return {"ok": True}


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
    return {**p, **{k: v for k, (v, _) in esperados(p, {})[0].items()}}


# ---------------- validación ----------------
@app.post("/api/validar")
def validar_etiqueta(request: Request, payload: dict = Body(...)):
    leido = payload.get("leido") or {}
    texto = payload.get("texto") or ""
    pid = payload.get("proceso_id")
    if pid:
        proceso = db.obtener_proceso(int(pid))
    else:
        proceso = db.buscar_proceso(norm_num(leido.get("proc")), norm_num(leido.get("lote")))
    por_coincidencia = None
    if proceso is None and not pid:
        proceso, por_coincidencia = mejor_proceso(leido, db.listar_procesos(solo_activos=True), texto)
    resultado = validar(leido, proceso, texto=texto)
    if por_coincidencia:
        resultado["avisos"].insert(0, f"PROC/LOTE no leídos con claridad: se identificó el proceso PROC {proceso['proc']}"
                                      f" / LOTE {proceso['lote']} en la base por coincidencia de {por_coincidencia}.")
    if payload.get("guardar", True):
        disp = request.headers.get("user-agent", "")[:120]
        resultado["id_historial"] = db.registrar_validacion(resultado, disp)
    return resultado


@app.post("/api/etiquetas")
def guardar_etiqueta(payload: dict = Body(...)):
    """Guarda la foto leída + texto OCR + campos (+ resultado) en etiquetas_leidas/AAAA-MM-DD/."""
    imagen = payload.get("imagen") or ""
    if "," not in imagen:
        raise HTTPException(400, "Falta la imagen")
    ahora = datetime.now()
    carpeta = ETIQUETAS / ahora.strftime("%Y-%m-%d")
    carpeta.mkdir(parents=True, exist_ok=True)
    modo = "registro" if payload.get("modo") == "registro" else "validacion"
    nombre = f"{ahora.strftime('%H%M%S')}_{modo}"
    campos = payload.get("campos") or {}
    if campos.get("proc") or campos.get("lote"):
        nombre += f"_P{norm_num(campos.get('proc')) or 'x'}_L{norm_num(campos.get('lote')) or 'x'}"
    n, base = 1, nombre
    while (carpeta / f"{nombre}.jpg").exists():
        n += 1
        nombre = f"{base}_{n}"
    (carpeta / f"{nombre}.jpg").write_bytes(base64.b64decode(imagen.split(",", 1)[1]))
    detalle = {"fecha_hora": ahora.isoformat(timespec="seconds"), "modo": modo, "campos": campos,
               "texto_ocr": payload.get("texto") or "", "resultado": payload.get("resultado")}
    (carpeta / f"{nombre}.json").write_text(json.dumps(detalle, ensure_ascii=False, indent=2), encoding="utf-8")
    (carpeta / f"{nombre}.txt").write_text(detalle["texto_ocr"], encoding="utf-8")
    return {"archivo": f"{carpeta.name}/{nombre}.jpg"}


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
