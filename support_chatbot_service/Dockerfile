# support_chatbot_service image. Mirrors the other services' Dockerfile shape
# (python:3.12-slim -> deps -> code -> uvicorn), with one addition: Node.js,
# installed only so this container can spawn `npx -y
# @modelcontextprotocol/server-postgres` as a stdio subprocess for the MCP
# client (see main.py's MCP module / CLAUDE.md) — every other service here is
# pure Python; this is the one runtime component that also needs Node.
FROM python:3.12-slim

WORKDIR /app

# NodeSource's setup script, not Debian's bundled `nodejs` package: bookworm's
# apt repo ships a dated Node build, and the MCP server package expects a
# reasonably current Node. curl/gnupg are only needed to fetch and trust that
# script, so both get removed again in the same layer to keep the image lean.
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# All seven of this service's own modules — the one service in this repo
# split across multiple files instead of a single main.py (see main.py's
# module docstring for why). *.py, not main.py alone, or every import in
# main.py would fail at container startup with a ModuleNotFoundError.
COPY *.py .

# 8008 is support-chatbot-service's internal port (auth=8002, profile=8001,
# image=8003, matcher=8004, recommendation=8005, session=8006, direct-msg=8007
# already taken).
EXPOSE 8008

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8008"]
