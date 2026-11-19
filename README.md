# Validador de Etiquetas

App web (celular, tablet o PC) para validar etiquetas de cajas de fruta con una foto:

- **Registrar**: guarda la etiqueta esperada de un proceso (PROC + LOTE), con foto o a mano; crea los maestros que falten.
- **Validar**: lee la foto (OCR en el navegador) y valida por bloques contra la base: **Productor** (CSG, región,
  provincia, comuna, GGN, SDP), **Planta** (CSP, región, provincia, comuna, FDA, CoC), **Exportadora** (CSE, nombre)
  y **Proceso** (lote, fecha, variedad, embalaje, peso, PLU, categoría). El calibre no se valida. Se pueden juntar
  2 o 3 fotos de la misma etiqueta. Lo leído parecido pero no igual queda como *dudoso*, nunca como correcto.

Base de datos: **SQL Server**. Las fotos leídas se guardan en `etiquetas_leidas/AAAA-MM-DD/`.

## Instalar con Docker (servidor)

```bash
git clone https://github.com/sarenasc/app_validador.git
cd app_validador
docker compose up -d --build
```

Abrir `http://<IP-del-servidor>:8520`. **La primera vez** la app pide la conexión a SQL Server (servidor, puerto,
base, usuario y contraseña): crea la base si no existe y todas las tablas, y guarda la conexión en `data/config.json`.
- SQL Server en el mismo equipo que Docker: usar servidor `host.docker.internal`.
- En Docker se usa usuario SQL (no autenticación de Windows). El usuario necesita permiso para crear la base
  (o crear la base antes y darle `db_owner`).
- Para cambiar la conexión: borrar `data/config.json` y reiniciar (`docker compose restart`).
- También se puede dar la conexión por variables de entorno (ver `docker-compose.yml`) y saltar el asistente.

Actualizar: `git pull && docker compose up -d --build`.

## Usar sin Docker (Windows)

```powershell
pip install -r requirements.txt
.\iniciar.bat
```

Requiere el driver "ODBC Driver 17/18 for SQL Server". Aquí sí se puede usar autenticación de Windows.

## Pruebas

```powershell
pip install -r requirements-dev.txt
python -m pytest -q tests                                   # con SQLite temporal
$env:VALIDADOR_TEST_MSSQL = "localhost"; python -m pytest -q tests   # además contra SQL Server real
```
