ARG BUILD_FROM
# hadolint ignore=DL3006
FROM ${BUILD_FROM}


# Copy Python requirements file
COPY requirements.txt /tmp/


RUN \
    apk add --no-cache \
        python3-dev=3.12.8-r1 \
    \
    && apk add --no-cache \
        py3-pip=24.3.1-r0 \
        python3=3.12.8-r1 \
    \
    && rm /usr/lib/python*/EXTERNALLY-MANAGED \
    && python3 -m ensurepip \
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
