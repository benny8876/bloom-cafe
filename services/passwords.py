"""Password hashing and verification (bcrypt with legacy SHA-256 migration)."""

import hashlib
import hmac

import bcrypt

BCRYPT_PREFIX = "$2"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _legacy_sha256(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith(BCRYPT_PREFIX):
        try:
            return bcrypt.checkpw(plain.encode(), stored.encode())
        except ValueError:
            return False
    expected = _legacy_sha256(plain)
    return hmac.compare_digest(expected, stored)


def needs_rehash(stored: str) -> bool:
    return not stored.startswith(BCRYPT_PREFIX)
