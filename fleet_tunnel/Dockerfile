FROM tailscale/tailscale:stable AS tailscale

FROM python:3.12-alpine

ARG BUILD_VERSION=0.1.1
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache socat
COPY --from=tailscale /usr/local/bin/tailscale /usr/local/bin/tailscale
COPY --from=tailscale /usr/local/bin/tailscaled /usr/local/bin/tailscaled

WORKDIR /app
COPY app ./app
COPY bootstrap.py ./bootstrap.py

CMD ["python", "/app/bootstrap.py"]
