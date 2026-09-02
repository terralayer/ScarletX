FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SCARLETX_HOST=0.0.0.0 \
    SCARLETX_PORT=8000 \
    SCARLETX_DATABASE_URL=sqlite:////config/scarletx.db \
    SCARLETX_USENET_INCOMPLETE_DIR=/downloads/incomplete \
    SCARLETX_USENET_COMPLETE_DIR=/downloads/complete \
    SCARLETX_GENERATED_DIR=/config/generated \
    SCARLETX_CACHE_DIR=/config/cache \
    SCARLETX_DEFAULT_MEDIA_ROOT=/tmp \
    SCARLETX_SECRET_KEY_FILE=/config/.scarletx-secret.key \
    SCARLETX_SETUP_TOKEN_FILE=/config/setup-token.json

# ScarletX owns the downloader, while mature system utilities handle repair and
# extraction. Enable Debian non-free so the official unrar package is available;
# fall back to unrar-free if a mirror omits it. 7-Zip remains the extraction fallback.
WORKDIR /app

RUN groupadd --gid 568 scarletx && useradd --uid 568 --gid 568 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin scarletx

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's/^Components: main$/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates par2 p7zip-full ffmpeg; \
    (apt-get install -y --no-install-recommends unrar || apt-get install -y --no-install-recommends unrar-free); \
    rm -rf /var/lib/apt/lists/*

# Dependency metadata is copied before application code so dependency layers stay
# reusable across ordinary source-only rebuilds. Omit blanket bytecode generation,
# then precompile only ScarletX and the startup-critical framework modules below.
COPY requirements.txt requirements-performance.txt pyproject.toml ./
RUN python -m pip install --no-cache-dir --disable-pip-version-check --no-compile -r requirements.txt \
    && (python -m pip install --no-cache-dir --disable-pip-version-check --no-compile -r requirements-performance.txt \
        || echo "SABCTools acceleration unavailable; using built-in yEnc decoder")

COPY scarletx ./scarletx

RUN python -m compileall -q \
      scarletx \
      /usr/local/lib/python3.12/site-packages/fastapi \
      /usr/local/lib/python3.12/site-packages/starlette \
      /usr/local/lib/python3.12/site-packages/pydantic \
      /usr/local/lib/python3.12/site-packages/sqlalchemy \
      /usr/local/lib/python3.12/site-packages/uvicorn \
      /usr/local/lib/python3.12/site-packages/anyio \
      /usr/local/lib/python3.12/site-packages/httpx \
      /usr/local/lib/python3.12/site-packages/httpcore \
      /usr/local/lib/python3.12/site-packages/cryptography \
      /usr/local/lib/python3.12/site-packages/pwdlib \
    && mkdir -p /config /config/generated /config/cache /downloads/incomplete /downloads/complete /downloads/failed /media /backups \
    && chown -R 568:568 /config /downloads /media /backups

VOLUME ["/config", "/downloads", "/media", "/backups"]
EXPOSE 8000
USER 568:568

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)); raise SystemExit(0 if d.get('app')=='ScarletX' else 1)"

CMD ["python", "-m", "scarletx"]
