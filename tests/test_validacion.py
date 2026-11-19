import pytest

from validador import datos_ejemplo, db
from validador.validacion import comparar, mejor_proceso, norm_num, validar

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
    r = validar({**LEIDO_OK, "proc": "99"}, db.buscar_proceso("99", "47"))
    # sin proceso registrado no es error: productor, planta y exportadora se validan contra los maestros
    assert r["estado"] == "ok"
    assert r["grupos"]["proceso"]["estado"] == "sin_proceso"
    assert r["grupos"]["productor"]["estado"] == "ok"
    r = validar({**LEIDO_OK, "proc": "99", "ggn": "1111111111111"}, None)
    assert r["estado"] == "error" and r["grupos"]["productor"]["estado"] == "error"


def test_productor_de_la_etiqueta_se_valida_con_su_maestro():
    # otra etiqueta con otro productor: sus datos se validan contra SU maestro, y el CSG no corresponde al proceso
    db.guardar("productor", {"csg": "200100", "region": "7", "provincia": "CURICO", "comuna": "TENO",
                             "ggn": "4060000000001"})
    db.guardar("sdp", {"csg": "200100", "sdp": "60001"})
    leido = {**LEIDO_OK, "csg": "200100", "prod_region": "7", "prod_provincia": "CURICO", "prod_comuna": "TENO",
             "ggn": "4060000000001", "sdp": "60001"}
    r = validar(leido, proceso())
    assert [f["campo"] for f in r["filas"] if f["estado"] == "error"] == ["csg", "sdp"]
    assert r["grupos"]["planta"]["estado"] == "ok"
    r = validar(leido, None)
    assert r["estado"] == "ok"


def test_codigo_inexistente_es_error_del_grupo():
    r = validar({**LEIDO_OK, "csp": "999999"}, None)
    assert r["grupos"]["planta"]["estado"] == "error"
    assert any("999999" in a for a in r["avisos"])


def test_sdp_y_variedad_fuera_de_maestro():
    r = validar({**LEIDO_OK, "sdp": "11111", "variedad": "OTRA"}, proceso())
    assert r["estado"] == "error"
    assert any("SDP 11111" in a for a in r["avisos"])
    assert any("OTRA" in a for a in r["avisos"])


def test_identifica_proceso_sin_proc_leido():
    # caso real: el OCR no leyó PROC pero sí lote, SDP, CSP, variedad y categoría
    leido = {"variedad": "AMELIA", "categoria": "CAT 1", "sdp": "50741", "csp": "171972", "lote": "47"}
    p, motivo = mejor_proceso(leido, db.listar_procesos(True))
    assert p["proc"] == "16" and "Lote" in motivo
    assert mejor_proceso({"lote": "47"}, db.listar_procesos(True)) == (None, None)


# Texto OCR real de una foto de celular (borrosa, con fondo): el parser separa pocos campos
TEXTO_CELULAR = """CcNICO
ILE - PPRODUCTO DE CHILE - PR
AMELIA ae
| PACKED BY / EMBALAD
CSG 155440 sds Le 072
4089453112834 FDA 1542 2646254
CoC :4069453462915
PROC: 16
+ 12.12 1b - NT [paces TPO2PG
LOTE: 47
ie CSE 89366
« SDP50741 yi |
----- 2a lectura -----
APRICOT DAMASCO 6 /CACHAPOAL /PICHIDEGUA
CSP:171972 EXPORTADORA AGUA SANTA S
CAT 1"""


def test_busca_valores_de_la_base_en_el_texto():
    leido = {"variedad": "AMELIA", "categoria": "CAT 1", "sdp": "50741", "csg": "155440", "proc": "16", "lote": "47"}
    r = validar(leido, proceso(), texto=TEXTO_CELULAR)
    est = {f["campo"]: f["estado"] for f in r["filas"]}
    for c in ("especie", "csp", "cse", "coc", "exportadora", "prod_provincia", "prod_comuna", "prod_region"):
        assert est[c] == "ok", c
    assert est["ggn"] == "dudoso"  # se leyó 4089... en vez de 4069...: no se da por bueno
    assert est["fda"] == "ok"  # "1542 2646254": el espacio del OCR no importa
    # el proceso también se identifica sin PROC/LOTE separados, buscándolos en el texto
    p, _ = mejor_proceso({}, db.listar_procesos(True), TEXTO_CELULAR)
    assert p and p["lote"] == "47"


def test_tolerancias_ocr():
    assert norm_num("I55440") == "155440"
    assert comparar("num", "15544O", "155440")[0]
    assert comparar("texto", "PICHIDEGUA", "PICHIDEGUA")[0]
    assert comparar("texto", "PICHIDECUA", "PICHIDEGUA") == (True, "lectura aproximada")
    assert not comparar("texto", "PEUMO", "PICHIDEGUA")[0]
    assert comparar("region", "VI", "6")[0]
    assert comparar("peso", "5,5", "5.50")[0]
    assert comparar("codigo", "DACO55TP02PGB", "DAC055TP02PGB")[0]
