"""SSL cert helpers."""

import logging
import os
import random

from OpenSSL import crypto

from ..const import LOGGER_NAME

_LOGGER = logging.getLogger(LOGGER_NAME)


def generate_ssl_certificates(
    path: str = "",
    key_file: str = "private.key",
    cert_file="cert.pem",
):
    """Generate certs."""
    k = crypto.PKey()
    k.generate_key(crypto.TYPE_RSA, 4096)
    cert = crypto.X509()
    cert.get_subject().C = "UK"
    cert.get_subject().L = "London"
    cert.get_subject().O = "Private"
    cert.get_subject().CN = "VPWebserver"
    cert.set_serial_number(random.randrange(100000))
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(315360000)
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(k)
    cert.sign(k, "sha512")

    # Verify cert directory exists and create if not
    if not os.path.isdir(path):
        os.mkdir(path)

    with open(f"{path}{cert_file}", "x", encoding="utf-8") as f:
        f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode("utf-8"))
    with open(f"{path}{key_file}", "x", encoding="utf-8") as f:
        f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k).decode("utf-8"))


def validate_ssl_certificates():
    """Validate certificate files."""
    if os.path.isfile("./connections/httpserver/certs/cert.pem") and os.path.isfile(
        "./connections/httpserver/certs/private.key"
    ):
        return True

    # Generate certs
    _LOGGER.info("Generating webserver certificates")
    try:
        generate_ssl_certificates(path="./connections/httpserver/certs/")
        return True  # noqa: TRY300
    except Exception as ex:  # noqa: BLE001
        _LOGGER.error("Error generating certificates - %s", ex)
        return False
