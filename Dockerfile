ARG BUILD_FROM=ghcr.io/hassio-addons/base:16.1.3
# hadolint ignore=DL3006
FROM ${BUILD_FROM}


# Copy Python requirements file
COPY requirements.txt /tmp/


RUN \
    apk add --no-cache \
    py3-pip=24.0-r2 \
    python3-dev=3.12.7-r0 \
    \
    && apk add --no-cache \
    python3=3.12.7-r0 \
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