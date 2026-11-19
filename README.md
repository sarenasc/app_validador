# Validador de Etiquetas

App web (celular, tablet o PC) para cajas de fruta con dos modos:

1. **Registrar**: saca una foto a una etiqueta correcta (o ingresa los datos a mano) y queda guardada como la
   *etiqueta esperada* del proceso (PROC + LOTE). Los productores, plantas, exportadoras, embalajes, etc. que no
   existan se crean en los maestros; si algo difiere de un maestro existente, la app avisa y deja actualizarlo.
2. **Validar**: saca una foto a una etiqueta de la línea; la app la lee y la compara con el proceso (se busca por
   PROC y LOTE leídos, o se elige a mano) y con los maestros. Muestra **ETIQUETA CORRECTA** o qué campo está mal
   y qué debería decir. El **calibre no se valida**.

Se validan: especie, variedad, CSG, región/provincia/comuna y GGN del productor, SDP (debe pertenecer al CSG),
CSP, región/provincia/comuna, FDA y CoC de la planta, CSE y nombre de la exportadora, embalaje, peso kg/lb y PLU
(del maestro de embalajes), PROC, lote, fecha de embalaje y categoría.

## Uso

```powershell
pip install -r requirements.txt
.\iniciar.bat
```

`iniciar.bat` ejecuta `python servidor.py --red` y muestra la dirección para abrir desde los celulares de la red
(ej. `http://192.168.x.x:8520`). Sin `--red` solo funciona en este PC.

- La foto se toma con el botón **Tomar foto** (usa la cámara del equipo; funciona también sin HTTPS).
- La lectura (OCR, Tesseract.js) se hace en el propio celular. La primera vez descarga el motor (~10 MB) desde
  internet; después queda en caché.
- Si un campo no se pudo leer queda en amarillo (**REVISAR**): se escribe a mano y se presiona **Validar**.
- La fecha impresa se interpreta como MM/DD/AA (11/18/26 = 18-nov-2026); se puede cambiar en **Maestros**.
- **Maestros**: se editan en pantalla o se pegan filas copiadas desde Excel.
- **Historial**: registra cada validación con su resultado.

Datos en `data/validador.db` (SQLite). Al iniciar por primera vez se carga un ejemplo (damasco Amelia,
PROC 16 / LOTE 47).

## Pruebas

```powershell
python -m pytest -q tests
```
