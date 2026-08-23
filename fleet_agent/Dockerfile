FROM python:3.12-alpine

ARG BUILD_VERSION=0.1.3
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

WORKDIR /app
COPY requirements.txt ./
RUN apk add --no-cache --virtual .build-deps \
      gcc \
      musl-dev \
      linux-headers \
    && pip install --no-cache-dir -r requirements.txt \
    && apk del .build-deps
COPY app ./app
COPY bootstrap.py ./bootstrap.py

CMD ["python", "/app/bootstrap.py"]
