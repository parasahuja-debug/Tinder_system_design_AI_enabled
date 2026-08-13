# matcher_service image. Mirrors profile_service's Dockerfile so every
# backend service builds the same predictable way.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# 8004 is matcher-service's internal port (auth=8002, profile=8001, image=8003 already taken).
EXPOSE 8004

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
