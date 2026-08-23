FROM python:3.12-alpine

ARG BUILD_VERSION=0.1.1
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

WORKDIR /app
COPY app ./app
COPY bootstrap.py ./bootstrap.py

CMD ["python", "/app/bootstrap.py"]

