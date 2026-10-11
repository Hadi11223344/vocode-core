"""
Voice Platform — Encryption Utilities
========================================

Provides Fernet symmetric encryption for sensitive data at rest
(API keys, auth tokens, etc.).

The encryption key is derived from the platform's JWT secret via
PBKDF2-HMAC-SHA256 (100k iterations). This means:
  - No extra secret to manage — uses the existing JWT_SECRET
  - Deterministic — same secret always produces the same Fernet key
  - If JWT_SECRET changes, existing encrypted values become unreadable
    (you'd need to re-encrypt or set ENCRYPTION_KEY explicitly)

For production, set ENCRYPTION_KEY as a proper Fernet key in .env:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Usage:
    from voice_platform.encryption import encrypt, decrypt

    cipher = encrypt("sk-abc123...")   # → "gAAAAABk..."
    plain  = decrypt(cipher)           # → "sk-abc123..."

SECURITY AUDIT NOTE (SEC-06):
  - Current: Fernet (cryptography library) uses AES-128-CBC + HMAC-SHA256.
  - Planned: Migrate to AES-256-GCM for stronger confidentiality and
    built-in authenticated encryption. This is a non-breaking change
    that can be rolled out via a dual-read / single-write migration:
    1. Deploy AES-256-GCM encrypt path (writes new format)
    2. Keep Fernet decrypt path (reads old format)
    3. Re-encrypt all stored secrets on first access
    4. Remove Fernet fallback once migration is complete.
"""

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from loguru import logger


def _get_or_create_salt() -> bytes:
    """Return a persistent per-instance salt. Generated once and stored in a file."""
    salt_path = os.path.join(os.path.dirname(__file__), ".encryption_salt")
    if os.path.exists(salt_path):
        with open(salt_path, "rb") as f:
            return f.read()
    # Generate new 16-byte random salt
    salt = os.urandom(16)
    with open(salt_path, "wb") as f:
        f.write(salt)
    logger.info(f"Generated new encryption salt at {salt_path}")
    return salt


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from an arbitrary string secret."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_get_or_create_salt(),
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


def _get_fernet() -> Fernet:
    """Build (and cache) the Fernet cipher from config."""
    from voice_platform.config import settings as _settings

    # Check for explicit encryption key (env var or settings)
    explicit_key = os.environ.get("ENCRYPTION_KEY") or _settings.encryption_key
    if explicit_key:
        return Fernet(explicit_key.encode() if isinstance(explicit_key, str) else explicit_key)

    # Fall back to deriving from JWT secret
    derived = _derive_key(_settings.jwt_secret)
    return Fernet(derived)


def encrypt(plaintext: str) -> str:
    """
    Encrypt a plaintext string. Returns a Fernet token (URL-safe base64).

    Args:
        plaintext: The sensitive value to encrypt (e.g. an API key).

    Returns:
        Fernet-encrypted ciphertext string.
    """
    if not plaintext:
        return plaintext
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """
    Decrypt a Fernet-encrypted string back to plaintext.

    If decryption fails (wrong key, corrupted data), returns the
    ciphertext as-is — this handles the migration period where old
    rows still contain plaintext values.

    Args:
        ciphertext: The encrypted value from the database.

    Returns:
        Decrypted plaintext string, or the original value if decryption fails.
    """
    if not ciphertext:
        return ciphertext
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        # Likely a plaintext value from before encryption was enabled.
        # Return as-is so existing keys keep working during migration.
        logger.debug(
            "Decrypt failed — value may be plaintext (pre-encryption migration)"
        )
        return ciphertext
