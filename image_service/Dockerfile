# image_service image. Mirrors auth_service/profile_service's Dockerfile so
# every backend service builds the same predictable way.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# 8003 is the internal port nginx's config will expect for image-service
# (8001 = profile-service, 8002 = auth-service already taken).
EXPOSE 8003

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
