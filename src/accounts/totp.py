"""Time-based One-Time Password (TOTP) implementation per RFC 6238.

Provides:
- Cryptographically secure base32 secret generation.
- Standard HMAC-SHA1 6-digit TOTP calculation with drift window tolerance.
- Standard otpauth:// URI formatting for Google Authenticator / 1Password / Authy.
- Single-use hashed backup recovery codes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

# Standard RFC 6238 constants
TOTP_DIGITS = 6
TOTP_INTERVAL = 30  # seconds
BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def generate_totp_secret(length: int = 32) -> str:
    """Generate a random base32 TOTP secret key."""
    return "".join(secrets.choice(BASE32_ALPHABET) for _ in range(length))


def get_totp_uri(
    secret: str,
    email: str,
    issuer: str = "AI POD",
) -> str:
    """Generate a standard otpauth:// URI for mobile authenticator apps."""
    clean_issuer = urllib.parse.quote(issuer)
    clean_email = urllib.parse.quote(email.strip().lower())
    label = f"{clean_issuer}:{clean_email}"
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret.upper().strip()}"
        f"&issuer={clean_issuer}"
        f"&algorithm=SHA1"
        f"&digits={TOTP_DIGITS}"
        f"&period={TOTP_INTERVAL}"
    )


def _compute_totp_code_at_counter(key_bytes: bytes, counter: int) -> str:
    """Compute 6-digit TOTP code for an integer time counter using HMAC-SHA1."""
    counter_bytes = struct.pack(">Q", counter)
    digest = hmac.new(key_bytes, counter_bytes, hashlib.sha1).digest()
    offset = digest[19] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def _decode_base32_secret(secret: str) -> bytes:
    """Decode a base32 secret string into bytes, padding as necessary."""
    clean = secret.strip().upper()
    missing_padding = (8 - len(clean) % 8) % 8
    padded = clean + ("=" * missing_padding)
    return base64.b32decode(padded, casefold=True)


def generate_totp_code(
    secret: str,
    timestamp: float | None = None,
) -> str:
    """Generate the current 6-digit TOTP code for a given base32 secret."""
    t = timestamp if timestamp is not None else time.time()
    counter = int(t / TOTP_INTERVAL)
    key_bytes = _decode_base32_secret(secret)
    return _compute_totp_code_at_counter(key_bytes, counter)


def verify_totp_code(
    secret: str,
    code: str,
    timestamp: float | None = None,
    window: int = 1,
) -> bool:
    """Verify a 6-digit TOTP code against a secret within the tolerance window.

    window=1 checks current interval as well as t-1 and t+1 (±30s drift).
    """
    clean_code = str(code).strip()
    if len(clean_code) != TOTP_DIGITS or not clean_code.isdigit():
        return False

    t = timestamp if timestamp is not None else time.time()
    current_counter = int(t / TOTP_INTERVAL)
    try:
        key_bytes = _decode_base32_secret(secret)
    except Exception:
        return False

    for offset in range(-window, window + 1):
        expected = _compute_totp_code_at_counter(key_bytes, current_counter + offset)
        if hmac.compare_digest(clean_code, expected):
            return True

    return False


def hash_backup_code(code: str) -> str:
    """Compute a SHA-256 hash of a backup recovery code."""
    normalized = code.strip().upper().replace("-", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_backup_codes(count: int = 8) -> list[str]:
    """Generate human-friendly recovery codes formatted as 'XXXX-XXXX'."""
    charset = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # unambiguous characters
    codes: list[str] = []
    for _ in range(count):
        part1 = "".join(secrets.choice(charset) for _ in range(4))
        part2 = "".join(secrets.choice(charset) for _ in range(4))
        codes.append(f"{part1}-{part2}")
    return codes


def verify_and_consume_backup_code(
    candidate_code: str,
    hashed_backup_codes: list[str],
) -> tuple[bool, list[str]]:
    """Verify if a candidate code matches any unused hashed backup code.

    If matched, returns (True, updated_hashed_codes_without_used_code).
    Otherwise returns (False, unchanged_hashed_codes).
    """
    candidate_hash = hash_backup_code(candidate_code)
    for idx, existing_hash in enumerate(hashed_backup_codes):
        if hmac.compare_digest(candidate_hash, existing_hash):
            remaining = [h for i, h in enumerate(hashed_backup_codes) if i != idx]
            return True, remaining
    return False, hashed_backup_codes
