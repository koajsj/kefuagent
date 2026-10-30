"""Authenticated encryption bound to the tenant and immutable credential reference."""

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from support_agent.errors import AppError


def cipher(master):
    try:
        key = base64.b64decode(master, altchars=b"-_", validate=True) if master else b""
        if len(key) != 32:
            raise ValueError
        return AESGCM(key)
    except (ValueError, binascii.Error):
        raise AppError(
            503, "credential_key_unavailable", "Credential encryption key unavailable"
        ) from None


def encrypt_secret(master, tenant_id, ref, secret):
    nonce = os.urandom(12)
    encrypted = cipher(master).encrypt(nonce, secret.encode(), f"v1:{tenant_id}:{ref}".encode())
    return base64.urlsafe_b64encode(nonce + encrypted).decode()


def decrypt_secret(master, tenant_id, ref, encoded):
    try:
        value = base64.b64decode(encoded, altchars=b"-_", validate=True)
        return (
            cipher(master)
            .decrypt(value[:12], value[12:], f"v1:{tenant_id}:{ref}".encode())
            .decode()
        )
    except (InvalidTag, ValueError, binascii.Error, UnicodeError):
        raise AppError(
            503, "credential_unavailable", "Stored credential cannot be decrypted"
        ) from None
