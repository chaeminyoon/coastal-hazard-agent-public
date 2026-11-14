FROM node:24-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM node:24-bookworm-slim AS node-runtime

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
    && apt-get install --no-install-recommends -y fontconfig fonts-noto-cjk libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 coastal

# Distribution-packaged Noto CJK includes its package license notices.
RUN fc-cache -f

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY requirements.service.txt ./
RUN python -m pip install --no-cache-dir -r requirements.service.txt

COPY backend/ ./backend/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY --from=frontend-build /build/frontend/dist/ ./frontend/dist/

RUN mkdir -p /data/artifacts /tmp/matplotlib \
    && chown -R coastal:coastal /data/artifacts /tmp/matplotlib

USER coastal

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "coastal_web.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
