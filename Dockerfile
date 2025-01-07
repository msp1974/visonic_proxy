ARG BUILD_FROM
# hadolint ignore=DL3006
FROM ${BUILD_FROM}


# Copy Python requirements file
COPY requirements.txt /tmp/


RUN \
    apk add --no-cache --virtual .build-dependencies \
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

# Build arguments
ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

# Labels
LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="Mark Paker" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="Home Assistant Community Add-ons" \
    org.opencontainers.image.authors="Mark Parker" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}