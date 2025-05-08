ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.21
# hadolint ignore=DL3006
FROM ${BUILD_FROM}


# Copy Python requirements file
COPY requirements.txt /tmp/


RUN \
    python3 -m ensurepip \
    && pip3 install -r /tmp/requirements.txt

COPY visonic_proxy /visonic_proxy
COPY run.sh /run.sh

# Set workdir to our add-on persistent data directory.
WORKDIR /data

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]

LABEL \
  io.hass.version="1.0.8" \
  io.hass.type="addon" \
  io.hass.arch="armhf|aarch64|i386|amd64|armv7"
