# Perseus Vault x CockroachDB — live interactive demo (web app container).
# Build from webdemo/:  docker build -t perseus-crdb-demo .
# Or via compose:       docker compose up -d --build   (also starts CockroachDB)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    HF_HOME=/app/.hf

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./app.py

# Bake the local embedding model into the image so runtime needs no network/API key.
RUN python -c "from model2vec import StaticModel; StaticModel.from_pretrained('minishlab/potion-base-8M'); print('model2vec cached')"

EXPOSE 8080
# Single worker keeps model + connections simple; a few threads for light concurrency.
CMD ["gunicorn", "-w", "1", "--threads", "4", "--timeout", "120", \
     "-b", "0.0.0.0:8080", "--access-logfile", "-", "app:app"]
