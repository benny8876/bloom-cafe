#!/usr/bin/env python3
"""Run the app over HTTPS for Chrome Web Bluetooth / Web USB support."""

import os
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
DEFAULT_KEY = ROOT / "certs" / "key.pem"
DEFAULT_CERT = ROOT / "certs" / "cert.pem"


def resolve_ssl_paths() -> tuple[str | None, str | None]:
    key = os.getenv("SSL_KEYFILE", str(DEFAULT_KEY))
    cert = os.getenv("SSL_CERTFILE", str(DEFAULT_CERT))
    if os.path.isfile(key) and os.path.isfile(cert):
        return key, cert
    return None, None


def main() -> None:
    port = int(os.getenv("PORT", "3000"))
    reload = os.getenv("RELOAD", "1") not in {"0", "false", "False"}
    ssl_keyfile, ssl_certfile = resolve_ssl_paths()

    kwargs: dict = {
        "host": "0.0.0.0",
        "port": port,
        "reload": reload,
    }

    if ssl_keyfile and ssl_certfile:
        kwargs["ssl_keyfile"] = ssl_keyfile
        kwargs["ssl_certfile"] = ssl_certfile
        print(f"HTTPS enabled on port {port}")
        print(f"  key:  {ssl_keyfile}")
        print(f"  cert: {ssl_certfile}")
    else:
        print("WARNING: No TLS certificate found.")
        print("Printer APIs require HTTPS when using a network IP in Chrome.")
        print("Generate certs with: python scripts/generate_dev_ssl.py")
        print(f"Starting HTTP on port {port} instead.")

    uvicorn.run("main:app", **kwargs)


if __name__ == "__main__":
    main()
