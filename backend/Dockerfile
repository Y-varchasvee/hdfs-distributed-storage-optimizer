FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/backend

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

RUN useradd --create-home --uid 1000 app && mkdir -p /data /datasets && chown -R app:app /data /datasets
USER app

ENV HDFSOPT_DATABASE_PATH=/data/metadata.db \
    HDFSOPT_SPOOL_DIR=/data/spool \
    HDFSOPT_DATASET_DIR=/datasets/raw \
    HDFSOPT_PROVENANCE_PATH=/datasets/provenance/manifest.json \
    HDFSOPT_DATANODE_HOST_MAP=

EXPOSE 8100
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8100/api/v1/health', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
