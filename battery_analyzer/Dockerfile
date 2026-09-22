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

CMD ["python", "-u", "/app/main.py"]
