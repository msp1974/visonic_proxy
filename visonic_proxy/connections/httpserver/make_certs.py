"""Make SSL certs for http server."""

import os
import random

from OpenSSL import crypto


def cert_gen(
    email_address: str = "",
    common_name: str = "Webserver",
    country: str = "UK",
    locality: str = "London",
    state: str = "",
    organisation: str = "Private",
    serial_number: int = random.randrange(100000),
    validity_start: int = 0,
    validity_end: int = 10 * 365 * 24 * 60 * 60,
    path: str = "",
    key_file: str = "private.key",
    cert_file="cert.pem",
):
    """Generate certs."""
    k = crypto.PKey()
    k.generate_key(crypto.TYPE_RSA, 4096)
    cert = crypto.X509()
    cert.get_subject().C = country
    # cert.get_subject().ST = state
    cert.get_subject().L = locality
    cert.get_subject().O = organisation
    # cert.get_subject().OU = ""
    cert.get_subject().CN = common_name
    # cert.get_subject().emailAddress = email_address
    cert.set_serial_number(serial_number)
    cert.gmtime_adj_notBefore(validity_start)
    cert.gmtime_adj_notAfter(validity_end)
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
