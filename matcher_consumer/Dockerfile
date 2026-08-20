# matcher_consumer image. Mirrors matcher_service's Dockerfile so every
# backend service builds the same predictable way — even though this
# service's real work is a background Kafka consumer thread, not the HTTP
# routes uvicorn serves (see main.py's module docstring).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# 8009 is matcher-consumer's internal port (8001-8008 already taken by
# every other service). Only ever serves /metrics and /health — see
# main.py's module docstring for why the real work isn't HTTP at all.
EXPOSE 8009

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8009"]
