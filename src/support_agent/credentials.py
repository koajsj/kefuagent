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


class Keyring:
    """Legacy v1 and explicit v2 envelopes; a version is authenticated with the tenant/ref."""

    def __init__(self, settings):
        import json
        import re

        self.keys = {}
        if settings.credential_keyring:
            try:
                self.keys = json.loads(settings.credential_keyring.get_secret_value())
                if not isinstance(self.keys, dict) or not 1 <= len(self.keys) <= 8:
                    raise ValueError
                if any(
                    not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", k) or not isinstance(v, str)
                    for k, v in self.keys.items()
                ):
                    raise ValueError
                for value in self.keys.values():
                    cipher(value)
            except (TypeError, ValueError):
                raise AppError(
                    503, "credential_key_unavailable", "Invalid credential keyring"
                ) from None
        if settings.credential_master_key:
            legacy = settings.credential_master_key.get_secret_value()
            if "legacy" in self.keys and self.keys["legacy"] != legacy:
                raise AppError(
                    503, "credential_key_unavailable", "Legacy key configuration conflicts"
                )
            self.keys["legacy"] = legacy
        self.active = settings.credential_active_key or "legacy"
        if settings.credential_active_key and self.active not in self.keys:
            raise AppError(503, "credential_key_unavailable", "Active credential key is missing")

    @staticmethod
    def version(encoded):
        import re

        if not encoded.startswith("k2."):
            return "legacy"
        parts = encoded.split(".")
        if len(parts) != 3 or not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", parts[1]):
            raise AppError(503, "credential_unavailable", "Invalid credential envelope")
        return parts[1]

    def seal(self, tenant_id, ref, secret, *, version=None):
        version = version or self.active
        key = self.keys.get(version)
        if not key:
            raise AppError(503, "credential_key_unavailable", "Credential key version unavailable")
        if version == "legacy":
            return encrypt_secret(key, tenant_id, ref, secret)
        nonce = os.urandom(12)
        value = cipher(key).encrypt(
            nonce, secret.encode(), f"v2:{version}:{tenant_id}:{ref}".encode()
        )
        return f"k2.{version}." + base64.urlsafe_b64encode(nonce + value).decode()

    def open(self, tenant_id, ref, encoded):
        version = self.version(encoded)
        key = self.keys.get(version)
        if not key:
            raise AppError(503, "credential_key_unavailable", "Credential key version unavailable")
        if version == "legacy":
            return decrypt_secret(key, tenant_id, ref, encoded)
        try:
            value = base64.b64decode(encoded.split(".")[2], altchars=b"-_", validate=True)
            return (
                cipher(key)
                .decrypt(value[:12], value[12:], f"v2:{version}:{tenant_id}:{ref}".encode())
                .decode()
            )
        except (InvalidTag, ValueError, binascii.Error, UnicodeError):
            raise AppError(
                503, "credential_unavailable", "Stored credential cannot be decrypted"
            ) from None
