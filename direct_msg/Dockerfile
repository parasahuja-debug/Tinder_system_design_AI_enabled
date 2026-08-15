# direct_msg image. Mirrors the other backend services' Dockerfile pattern
# so every service builds the same predictable way.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# 8007 is the next open internal port after session-service's 8006.
EXPOSE 8007

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8007"]
