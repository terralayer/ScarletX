FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SCARLETX_HOST=0.0.0.0 \
    SCARLETX_PORT=8690 \
    SCARLETX_NO_BROWSER=1 \
    SCARLETX_DATABASE_URL=sqlite:////config/scarletx.db \
    SCARLETX_USENET_INCOMPLETE_DIR=/downloads/incomplete \
    SCARLETX_USENET_COMPLETE_DIR=/downloads/complete \
    SCARLETX_GENERATED_DIR=/config/generated \
    SCARLETX_CACHE_DIR=/config/cache \
    SCARLETX_DEFAULT_MEDIA_ROOT=/tmp

WORKDIR /app

# ScarletX owns the downloader, while mature system utilities handle repair and
# extraction. Enable Debian non-free so the official unrar package is available;
# fall back to unrar-free if a mirror omits it. 7-Zip remains the extraction fallback.
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's/^Components: main$/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates par2 p7zip-full ffmpeg; \
    (apt-get install -y --no-install-recommends unrar || apt-get install -y --no-install-recommends unrar-free); \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-performance.txt pyproject.toml ./
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt \
    && (python -m pip install --no-cache-dir --disable-pip-version-check -r requirements-performance.txt \
        || echo "SABCTools acceleration unavailable; using built-in yEnc decoder")

COPY scarletx ./scarletx
COPY README.md RELEASE-NOTES-0.3.6.md BUILD-INFO.txt ./

RUN mkdir -p /config /config/generated /config/cache /downloads/incomplete /downloads/complete /downloads/failed /media /backups

VOLUME ["/config", "/downloads", "/media", "/backups"]
EXPOSE 8690

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8690/api/health', timeout=3)); raise SystemExit(0 if d.get('app')=='ScarletX' else 1)"

CMD ["python", "-m", "uvicorn", "scarletx.main:app", "--host", "0.0.0.0", "--port", "8690"]
