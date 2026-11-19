"""Datos de ejemplo (de una etiqueta real de damasco) para los tests. La app parte con la base vacía."""

from . import db


def cargar():
    db.guardar("productor", {"csg": "155440", "nombre": "Productor ejemplo", "region": "6",
                             "provincia": "CACHAPOAL", "comuna": "PICHIDEGUA", "ggn": "4069453112834"})
    db.guardar("sdp", {"csg": "155440", "sdp": "50741", "descripcion": "Sitio ejemplo"})
    db.guardar("planta", {"csp": "171972", "nombre": "Planta Almahue", "region": "6", "provincia": "CACHAPOAL",
                          "comuna": "PICHIDEGUA", "fda": "15422646254", "coc": "4069453462915"})
    db.guardar("exportadora", {"cse": "89366", "nombre": "EXPORTADORA AGUA SANTA"})
    db.guardar("especie", {"especie": "DAMASCO", "nombre_ingles": "APRICOT"})
    for esp, ing in (("CIRUELA", "PLUM"), ("DURAZNO", "PEACH"), ("NECTARIN", "NECTARINE"), ("CEREZA", "CHERRY")):
        db.guardar("especie", {"especie": esp, "nombre_ingles": ing})
    db.guardar("variedad", {"especie": "DAMASCO", "variedad": "AMELIA"})
    db.guardar("embalaje", {"codigo": "DAC055TP02PGB", "especie": "DAMASCO", "peso_kg": "5.5",
                            "peso_lb": "12.12", "plu": "3302"})
    for c in ("CAT 1", "CAT 2", "CAT 3"):
        db.guardar("categoria", {"categoria": c})
    db.guardar_proceso({"proc": "16", "lote": "47", "fecha": "2026-11-18", "csg": "155440", "sdp": "50741",
                        "csp": "171972", "cse": "89366", "embalaje": "DAC055TP02PGB", "especie": "DAMASCO",
                        "variedad": "AMELIA", "categoria": "CAT 1", "plu": "3302",
                        "observacion": "Ejemplo cargado desde etiqueta"})

