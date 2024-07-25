ARG BUILD_FROM=ghcr.io/hassio-addons/base:16.1.3
# hadolint ignore=DL3006
FROM ${BUILD_FROM}


# Copy Python requirements file
COPY requirements.txt /tmp/


RUN \
    apk add --no-cache \
    py3-pip=24.0-r2 \
    python3-dev=3.12.3-r1 \
    \
    && apk add --no-cache \
    python3=3.12.3-r1 \
    \
    && rm /usr/lib/python*/EXTERNALLY-MANAGED \
    && python3 -m ensurepip \
    && pip3 install -r /tmp/requirements.txt

COPY visonic_proxy /visonic_proxy

RUN \
    apk add --no-cache \
    openssl \
    && openssl req -x509 -newkey rsa:4096 -keyout private.key -out cert.pem -sha256 -days 3650 -nodes -subj "/C=UK/L=London/O=Private/OU=Development/CN=Webserver" \
    && mv private.key /visonic_proxy/visonic_proxy/connections/certs/private.key \
    && mv cert.pem /visonic_proxy/visonic_proxy/connections/certs/cert.pem


# Set workdir to our add-on persistent data directory.
WORKDIR /data

RUN chmod a+x /visonic_proxy/run.sh

CMD [ "/visonic_proxy/run.sh" ]