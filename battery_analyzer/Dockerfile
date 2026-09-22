FROM python:3.13-alpine

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

ENV APP_VERSION="${BUILD_VERSION}" \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir aiohttp==3.12.15

WORKDIR /app
COPY app/ /app/

# Native Docker health check (Home Assistant app-linter requirement)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=3).read()" || exit 1

CMD ["python", "-u", "/app/main.py"]
