#!/usr/bin/env python3
"""Generate a self-signed TLS certificate for local HTTPS development."""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CERT_DIR = ROOT / "certs"
KEY_PATH = CERT_DIR / "key.pem"
CERT_PATH = CERT_DIR / "cert.pem"


def local_ipv4_addresses() -> list[str]:
    addresses = {"127.0.0.1"}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addresses.add(info[4][0])
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            addresses.add(sock.getsockname()[0])
    except OSError:
        pass

    return sorted(addresses)


def build_san_extension() -> str:
    entries = ["DNS:localhost", "IP:127.0.0.1"]
    for address in local_ipv4_addresses():
        try:
            ipaddress.IPv4Address(address)
        except ValueError:
            continue
        entry = f"IP:{address}"
        if entry not in entries:
            entries.append(entry)
    return f"subjectAltName={','.join(entries)}"


def main() -> int:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    san = build_san_extension()

    command = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-keyout",
        str(KEY_PATH),
        "-out",
        str(CERT_PATH),
        "-days",
        "825",
        "-nodes",
        "-subj",
        "/CN=localhost",
        "-addext",
        san,
    ]

    try:
        subprocess.run(command, check=True)
    except FileNotFoundError:
        print("openssl is required but was not found on PATH.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"openssl failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1

    print(f"Wrote {KEY_PATH}")
    print(f"Wrote {CERT_PATH}")
    print(f"SAN: {san}")
    print()
    print("Start HTTPS with:")
    print("  python run_https.py")
    print()
    print("In Chrome, open the https:// URL and accept the certificate warning once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
