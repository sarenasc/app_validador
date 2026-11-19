FROM python:3.12-slim-bookworm

# Driver ODBC 18 de Microsoft para SQL Server
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg2 ca-certificates unixodbc \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY servidor.py .
COPY validador ./validador
COPY web ./web

# data/ guarda config.json (conexión) y etiquetas_leidas/ las fotos: montarlos como volúmenes
VOLUME ["/app/data", "/app/etiquetas_leidas"]
EXPOSE 8520
CMD ["uvicorn", "servidor:app", "--host", "0.0.0.0", "--port", "8520"]
