# auth_service image. Slim base keeps the container small; we only need Python.
FROM python:3.12-slim

WORKDIR /app

# Install deps first, as their own layer, so code edits don't bust the pip cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# 8002 is the internal port nginx's config already expects for auth-service.
EXPOSE 8002

# --host 0.0.0.0 so the port is reachable from other containers on the compose
# network (not just localhost inside this container).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
