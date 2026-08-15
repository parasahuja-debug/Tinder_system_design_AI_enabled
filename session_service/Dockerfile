# session_service image. Mirrors the other backend services' Dockerfile
# pattern so every service builds the same predictable way.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# 8006 is the next open internal port after recommendation-service's 8005.
EXPOSE 8006

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8006"]
