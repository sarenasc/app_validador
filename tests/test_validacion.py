import pytest

from validador import datos_ejemplo, db
from validador.validacion import comparar, norm_num, validar

LEIDO_OK = {
    "especie": "DAMASCO", "variedad": "AMELIA", "csg": "155440", "prod_region": "6", "prod_provincia": "CACHAPOAL",
    "prod_comuna": "PICHIDEGUA", "ggn": "4069453112834", "csp": "171972", "planta_region": "6",
    "planta_provincia": "CACHAPOAL", "planta_comuna": "PICHIDEGUA", "fda": "15422646254", "coc": "4069453462915",
    "cse": "89366", "exportadora": "EXPORTADORA AGUA SANTA S", "proc": "16", "lote": "47", "sdp": "50741",
    "embalaje": "DAC055TP02PGB", "peso_kg": "5.5", "peso_lb": "12.12", "plu": "3302", "fecha": "2026-11-18",
    "categoria": "CAT 1", "calibre": "68",
}


@pytest.fixture(autouse=True)
def base_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.crear_tablas()
    datos_ejemplo.cargar()


def proceso():
    return db.buscar_proceso("16", "47")


def test_etiqueta_correcta():
    r = validar(LEIDO_OK, proceso())
    assert r["estado"] == "ok", [f for f in r["filas"] if f["estado"] == "error"] + r["avisos"]


def test_detecta_ggn_y_lote_incorrectos():
    r = validar({**LEIDO_OK, "ggn": "4069453112835", "lote": "48"}, proceso())
    errores = {f["campo"] for f in r["filas"] if f["estado"] == "error"}
    assert r["estado"] == "error"
    assert errores == {"ggn", "lote"}


def test_calibre_no_se_valida():
    r = validar({**LEIDO_OK, "calibre": "99"}, proceso())
    assert r["estado"] == "ok"


def test_campo_no_leido_queda_en_revisar():
    leido = dict(LEIDO_OK)
    del leido["fda"]
    r = validar(leido, proceso())
    assert r["estado"] == "revisar"
    assert r["n_no_leidos"] == 1


def test_sin_proceso_valida_contra_maestros():
    r = validar({**LEIDO_OK, "proc": "99", "comuna": "X"}, db.buscar_proceso("99", "47"))
    assert r["estado"] == "error"
    # los datos del productor igual se comparan con el maestro
    assert next(f for f in r["filas"] if f["campo"] == "ggn")["estado"] == "ok"


def test_sdp_y_variedad_fuera_de_maestro():
    r = validar({**LEIDO_OK, "sdp": "11111", "variedad": "OTRA"}, proceso())
    assert r["estado"] == "error"
    assert any("SDP 11111" in a for a in r["avisos"])
    assert any("OTRA" in a for a in r["avisos"])


def test_tolerancias_ocr():
    assert norm_num("I55440") == "155440"
    assert comparar("num", "15544O", "155440")[0]
    assert comparar("texto", "PICHIDEGUA", "PICHIDEGUA")[0]
    assert comparar("texto", "PICHIDECUA", "PICHIDEGUA") == (True, "lectura aproximada")
    assert not comparar("texto", "PEUMO", "PICHIDEGUA")[0]
    assert comparar("region", "VI", "6")[0]
    assert comparar("peso", "5,5", "5.50")[0]
    assert comparar("codigo", "DACO55TP02PGB", "DAC055TP02PGB")[0]
