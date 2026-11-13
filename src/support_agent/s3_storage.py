"""Private path-style S3 storage using signed, bounded requests and immutable UUID keys.

Configuration is deployment-owned. No URL, bucket or path is supplied by an upload.
Physical version-aware deletion remains blocked with the rest of knowledge erasure.
"""

import hashlib
import hmac
import ssl
import time
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpcore

LIMIT = 5 * 1024 * 1024


class S3DocumentStorage:
    def __init__(self, settings):
        self.endpoint = settings.s3_endpoint.rstrip("/")
        self.bucket = settings.s3_bucket
        self.region = settings.s3_region
        self.prefix = settings.s3_prefix.strip("/")
        self.access = settings.s3_access_key.get_secret_value()
        self.secret = settings.s3_secret_key.get_secret_value()
        self.token = (
            settings.s3_session_token.get_secret_value() if settings.s3_session_token else None
        )

    def _path(self, tenant_id, document_id):
        parts = [self.bucket, self.prefix, str(UUID(str(tenant_id))), str(UUID(str(document_id)))]
        return "/" + "/".join(quote(part, safe="/-_.~") for part in parts if part)

    def _request(self, method, tenant_id, document_id, body=b"", *, exclusive=False):
        path = self._path(tenant_id, document_id)
        now = datetime.now(UTC)
        date, timestamp = now.strftime("%Y%m%d"), now.strftime("%Y%m%dT%H%M%SZ")
        digest = hashlib.sha256(body).hexdigest()
        headers = {
            "host": urlsplit(self.endpoint).netloc,
            "x-amz-date": timestamp,
            "x-amz-content-sha256": digest,
        }
        if self.token:
            headers["x-amz-security-token"] = self.token
        if exclusive:
            headers["if-none-match"] = "*"
        names = ";".join(sorted(headers))
        canonical_headers = "".join(f"{name}:{headers[name].strip()}\n" for name in sorted(headers))
        canonical = "\n".join((method, path, "", canonical_headers, names, digest))
        scope = f"{date}/{self.region}/s3/aws4_request"
        sign_text = "\n".join(
            ("AWS4-HMAC-SHA256", timestamp, scope, hashlib.sha256(canonical.encode()).hexdigest())
        )
        key = ("AWS4" + self.secret).encode()
        for item in (date, self.region, "s3", "aws4_request"):
            key = hmac.new(key, item.encode(), hashlib.sha256).digest()
        signature = hmac.new(key, sign_text.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access}/{scope}, SignedHeaders={names}, Signature={signature}"
        )
        deadline = time.monotonic() + 20
        try:
            with httpcore.ConnectionPool(
                ssl_context=ssl.create_default_context(), retries=0, max_connections=1
            ) as pool:
                with pool.stream(
                    method,
                    self.endpoint + path,
                    headers=headers,
                    content=body,
                    extensions={"timeout": {"connect": 5, "read": 5, "write": 5, "pool": 5}},
                ) as response:
                    if response.status == 404:
                        raise FileNotFoundError("Private object not found")
                    if response.status == 412 and exclusive:
                        return None
                    if response.status not in {200, 204}:
                        raise OSError("Private object request was rejected")
                    result = bytearray()
                    for part in response.iter_stream():
                        result.extend(part)
                        if len(result) > LIMIT or time.monotonic() > deadline:
                            raise OSError("Private object transfer limit exceeded")
                    return bytes(result)
        except (httpcore.TimeoutException, httpcore.NetworkError, httpcore.ProtocolError):
            raise OSError("Private object storage unavailable") from None

    def write(self, tenant_id, document_id, content):
        if not content or len(content) > LIMIT:
            raise OSError("Private object size exceeded")
        if self._request("PUT", tenant_id, document_id, content, exclusive=True) is None:
            if self.read(tenant_id, document_id) != content:
                raise OSError("Immutable private object content differs")

    def read(self, tenant_id, document_id):
        return self._request("GET", tenant_id, document_id)

    def exists(self, tenant_id, document_id):
        try:
            self.read(tenant_id, document_id)
            return True
        except FileNotFoundError:
            return False

    def delete(self, tenant_id, document_id):
        raise OSError("Version-aware object erasure requires a complete approved dependency plan")
