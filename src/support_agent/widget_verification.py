"""Disposable HTTPS ownership fetch. No database, credentials, redirects or private IPs."""

import hashlib
import json
import ssl
import sys
import time

import httpcore

from support_agent.providers import PublicNetworkBackend


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read(2048))
        from support_agent.services.widget_identity import normalize_origin

        origin = normalize_origin(payload["origin"])
        deadline = time.monotonic() + 8
        with httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PublicNetworkBackend(),
            retries=0,
            max_connections=1,
        ) as pool:
            with pool.stream(
                "GET",
                origin + "/.well-known/kefuagent-site-verification",
                headers={"Accept": "text/plain", "Accept-Encoding": "identity"},
                extensions={"timeout": {"connect": 3, "read": 3, "write": 3, "pool": 3}},
            ) as response:
                if response.status != 200:
                    return
                content = b""
                for chunk in response.iter_stream():
                    if len(content) + len(chunk) > 256 or time.monotonic() > deadline:
                        return
                    content += chunk
                print(hashlib.sha256(content.strip()).hexdigest())
    except Exception:
        # Never print fetched data, network errors, tracebacks or the challenge.
        return


if __name__ == "__main__":
    main()
