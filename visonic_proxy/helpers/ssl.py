"""SSL cert helpers."""

import logging
import os
from pathlib import Path
import secrets

from ..const import LOGGER_NAME

_LOGGER = logging.getLogger(LOGGER_NAME)

ADDON_CERTS_PATH = "/data/certs"


def get_ssl_certs_path(
    ssl_cert_path: str, is_addon: bool = False, base_dir: str | None = None
) -> str:
    """Resolve persistent certificate directory for add-on or standalone mode."""
    if is_addon:
        return ADDON_CERTS_PATH
    if os.path.isabs(ssl_cert_path):
        return ssl_cert_path
    root = base_dir or str(Path(__file__).resolve().parent.parent)
    return str(Path(root) / ssl_cert_path)


def generate_ssl_certificates(
    path: str = "",
    key_file: str = "private.key",
    cert_file: str = "cert.pem",
):
    """Generate self-signed TLS certificates with secure serial and key permissions."""
    from OpenSSL import crypto  # noqa: PLC0415

    k = crypto.PKey()
    k.generate_key(crypto.TYPE_RSA, 4096)
    cert = crypto.X509()
    cert.get_subject().C = "UK"
    cert.get_subject().L = "London"
    cert.get_subject().O = "Private"
    cert.get_subject().CN = "VisonicProxy"
    cert.set_serial_number(secrets.randbits(63) or 1)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(315360000)
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(k)
    cert.sign(k, "sha512")

    cert_dir = Path(path)
    cert_dir.mkdir(parents=True, exist_ok=True)

    cert_path = cert_dir / cert_file
    key_path = cert_dir / key_file

    cert_path.write_bytes(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
    key_path.write_bytes(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
    if os.name != "nt":
        os.chmod(key_path, 0o600)


def validate_ssl_certificates(path: str) -> bool:
    """Validate certificate files and generate them if missing."""
    cert_dir = Path(path)
    if (cert_dir / "cert.pem").is_file() and (cert_dir / "private.key").is_file():
        _LOGGER.info("SSL Certificates validated at %s", path)
        return True

    _LOGGER.info("Generating SSL Certificates at %s", path)
    try:
        generate_ssl_certificates(path=path)
    except Exception as ex:  # noqa: BLE001
        _LOGGER.error("Error generating certificates - %s", ex)
        return False
    else:
        return True
