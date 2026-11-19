"""Prueba de integración contra SQL Server real (opcional).

Corre solo si se define VALIDADOR_TEST_MSSQL con el servidor (ej. "localhost"). Usa autenticación de Windows
salvo que se definan VALIDADOR_TEST_MSSQL_USER / VALIDADOR_TEST_MSSQL_PASSWORD. Crea una base temporal
validador_test_<aleatorio> y la elimina al terminar.

    $env:VALIDADOR_TEST_MSSQL = "localhost"; python -m pytest -q tests/test_sqlserver.py
"""

import os
import uuid

import pytest

from validador import datos_ejemplo, db
from validador.validacion import validar

SERVIDOR = os.environ.get("VALIDADOR_TEST_MSSQL")
pytestmark = pytest.mark.skipif(not SERVIDOR, reason="definir VALIDADOR_TEST_MSSQL para probar con SQL Server")


@pytest.fixture
def base_sqlserver(tmp_path, monkeypatch):
    import pyodbc

    monkeypatch.setattr(db, "CONFIG_PATH", tmp_path / "config.json")
    usuario = os.environ.get("VALIDADOR_TEST_MSSQL_USER", "")
    cfg = {"servidor": SERVIDOR, "puerto": os.environ.get("VALIDADOR_TEST_MSSQL_PORT", ""),
           "base": f"validador_test_{uuid.uuid4().hex[:8]}", "usuario": usuario,
           "clave": os.environ.get("VALIDADOR_TEST_MSSQL_PASSWORD", ""), "windows": not usuario,
           "confiar_certificado": True}
    ok, msg = db.probar_conexion(cfg)
    assert ok, msg
    db.inicializar_sqlserver(cfg)
    yield cfg
    con = pyodbc.connect(db._cadena(cfg, "master"), autocommit=True)
    con.cursor().execute(f"ALTER DATABASE [{cfg['base']}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                         f"DROP DATABASE [{cfg['base']}]")
    con.close()


def test_crea_base_tablas_y_valida(base_sqlserver):
    assert (db.CONFIG_PATH).exists()
    db.crear_tablas()  # idempotente: al reiniciar no falla
    datos_ejemplo.cargar()
    db.guardar("productor", {"csg": "155440", "ggn": "4069453112834", "nombre": "Actualizado"})  # upsert
    assert db.obtener("productor", csg="155440")["nombre"] == "Actualizado"
    p = db.buscar_proceso("16", "47")
    assert p and isinstance(p["id"], int)
    leido = {"csg": "155440", "ggn": "4069453112834", "csp": "171972", "proc": "16", "lote": "48"}
    r = validar(leido, p)
    est = {f["campo"]: f["estado"] for f in r["filas"]}
    assert est["csg"] == est["ggn"] == est["csp"] == "ok" and est["lote"] == "error" and r["estado"] == "error"
    vid = db.registrar_validacion(r, "test")
    assert isinstance(vid, int) and db.listar_validaciones(5)[0]["id"] == vid
    p2 = db.guardar_proceso({**p, "lote": "48"})
    assert p2["id"] != p["id"] and len(db.listar_procesos()) == 2
    db.eliminar("sdp", {"csg": "155440", "sdp": "50741"})
    assert db.obtener("sdp", csg="155440", sdp="50741") is None
