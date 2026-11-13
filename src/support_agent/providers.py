"""Small Chat Completions adapter. No SDK objects escape the boundary."""

import ipaddress
import json
import math
import re
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from threading import BoundedSemaphore
from typing import Protocol
from urllib.parse import urlsplit

import httpcore

from support_agent.errors import AppError


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Completion:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    attempts: int = 1
    tool_calls: tuple[ModelToolCall, ...] = ()
    refused: bool = False
    embedding: tuple[float, ...] = ()


class Provider(Protocol):
    def complete(
        self, *, base_url, api_key, model, messages, runtime, tools=None
    ) -> Completion: ...


class ProviderFailure(Exception):
    def __init__(self, category, attempts=1, input_tokens=None, output_tokens=None):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.category = category
        self.attempts = attempts
        super().__init__(category)


def normalize_status(status, body=b""):
    try:
        error = json.loads(body).get("error", {})
        code, kind, parameter = (
            error.get(key) if isinstance(error.get(key), str) else None
            for key in ("code", "type", "param")
        )
    except (ValueError, AttributeError, TypeError):
        code = kind = parameter = None
    if status == 429 and (
        {code, kind}
        & {"insufficient_quota", "billing_hard_limit_reached", "organization_usage_limit_exceeded"}
    ):
        return "quota_exhausted"
    if status == 404 and code in {"model_not_found", "model_not_available"}:
        return "model_unavailable"
    if (
        status == 400
        and code in {"unsupported_parameter", "unsupported_value"}
        and parameter in {"tools", "tool_choice", "parallel_tool_calls"}
    ):
        return "tools_not_supported"
    if status in (401, 403):
        return "authentication_failed"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "provider_unavailable"
    return "request_rejected"


def validate_base_url(url, allowed_hosts):
    try:
        parsed = urlsplit(url or "")
        valid = (
            parsed.scheme == "https"
            and parsed.hostname in allowed_hosts
            and parsed.netloc == parsed.hostname
            and not parsed.query
            and not parsed.fragment
            and all(
                c in "/abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for c in parsed.path
            )
        )
        if not valid:
            raise AppError(
                422, "invalid_provider_url", "Use an approved HTTPS provider hostname and path"
            )
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            return url.rstrip("/")
    except ValueError:
        pass
    raise AppError(422, "invalid_provider_url", "Use an approved HTTPS provider hostname and path")


class PublicNetworkBackend(httpcore.SyncBackend):
    """Resolve once, reject every non-public answer, connect the checked IP; TLS retains hostname."""

    def __init__(self, private_hosts=()):
        self.private_hosts = frozenset(private_hosts)

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            raise httpcore.ConnectError("DNS unavailable") from None
        addresses = list(dict.fromkeys(item[4][0] for item in answers))
        private_allowed = host in self.private_hosts

        def permitted(addr):
            ip = ipaddress.ip_address(addr)
            if (
                ip.is_multicast
                or ip.is_link_local
                or ip.is_unspecified
                or (ip.is_reserved and not ip.is_loopback)
            ):
                return False
            if ip.is_global:
                return True
            # Limit private opt-in to loopback, RFC1918 and IPv6 ULA. Metadata/link-local stays denied.
            ranges = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
            return private_allowed and (
                ip.is_loopback or any(ip in ipaddress.ip_network(net) for net in ranges)
            )

        if not addresses or any(not permitted(addr) for addr in addresses):
            raise ProviderFailure("unsafe_endpoint", attempts=0)
        return super().connect_tcp(addresses[0], port, timeout, local_address, socket_options)


def parse_completion(body, attempts, *, allow_tools=False):
    input_tokens = output_tokens = None
    try:
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError
        usage = value.get("usage")
        if usage is None:
            usage = {}
        if not isinstance(usage, dict):
            raise ValueError

        def tokens(key):
            number = usage.get(key)
            if number is not None and (type(number) is not int or not 0 <= number <= 1000000000):
                raise ValueError
            return number

        # A truncated/invalid completion can still report valid billable usage.
        input_tokens = tokens("prompt_tokens")
        output_tokens = tokens("completion_tokens")
        if not isinstance(value.get("choices"), list):
            raise ValueError
        choice = value["choices"][0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError
        message = choice["message"]
        if allow_tools:
            refusal = message.get("refusal")
            if refusal or choice["finish_reason"] == "content_filter":
                # A contradictory response must never turn a refusal into a tool action.
                if message.get("tool_calls"):
                    raise ValueError
                return Completion("", input_tokens, output_tokens, attempts, refused=True)
            calls = message.get("tool_calls")
            if calls:
                if (
                    choice["finish_reason"] != "tool_calls"
                    or not isinstance(calls, list)
                    or len(calls) > 4
                ):
                    raise ValueError
                checked = []
                for call in calls:
                    function = call["function"]
                    if (
                        call["type"] != "function"
                        or not isinstance(call["id"], str)
                        or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", call["id"])
                        or not isinstance(function["name"], str)
                        or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", function["name"])
                        or not isinstance(function["arguments"], str)
                        or len(function["arguments"].encode()) > 16384
                    ):
                        raise ValueError
                    checked.append(
                        ModelToolCall(call["id"], function["name"], function["arguments"])
                    )
                if len({c.id for c in checked}) != len(checked):
                    raise ValueError
                # Ignore free text next to a tool request; only the final stop is user-visible.
                return Completion("", input_tokens, output_tokens, attempts, tuple(checked))
        if choice["finish_reason"] != "stop" or message.get("tool_calls") or message.get("refusal"):
            raise ValueError
        content = message["content"]
        if not isinstance(content, str) or not content.strip() or len(content.encode()) > 32768:
            raise ValueError
        return Completion(content, input_tokens, output_tokens, attempts)
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        raise ProviderFailure("invalid_response", attempts, input_tokens, output_tokens) from None


def parse_embedding(body, attempts):
    tokens = None
    try:
        value = json.loads(body)
        usage = value.get("usage", {})
        tokens = usage.get("prompt_tokens")
        if tokens is not None and (type(tokens) is not int or not 0 <= tokens <= 1000000000):
            raise ValueError
        data = value["data"]
        if len(data) != 1 or data[0].get("index") != 0:
            raise ValueError
        vector = data[0]["embedding"]
        if (
            not isinstance(vector, list)
            or len(vector) != 1536
            or not any(vector)
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)
        ):
            raise ValueError
        return Completion("", tokens, 0, attempts, embedding=tuple(vector))
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise ProviderFailure("invalid_embedding", attempts, tokens, 0) from None


_PROVIDER_SLOTS = BoundedSemaphore(8)


class OpenAICompatibleProvider:
    def __init__(self, allowed_hosts, *, enabled=True, private_hosts=()):
        self.allowed_hosts = allowed_hosts
        self.enabled = enabled
        self.private_hosts = tuple(private_hosts)

    def complete(self, **kwargs):
        if not self.enabled:
            raise ProviderFailure("external_models_disabled", attempts=0)
        if not _PROVIDER_SLOTS.acquire(blocking=False):
            raise ProviderFailure("provider_busy", attempts=0)
        try:
            return self._complete_bounded(**kwargs)
        finally:
            _PROVIDER_SLOTS.release()

    def _complete_bounded(
        self, *, base_url, api_key, model, messages, runtime, tools=None, embedding_input=None
    ):
        validate_base_url(base_url, self.allowed_hosts)
        payload = json.dumps(
            {
                "allowed_hosts": self.allowed_hosts,
                "private_hosts": self.private_hosts,
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
                "messages": messages,
                "runtime": runtime,
                "tools": tools,
                "embedding_input": embedding_input,
            }
        ).encode()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import signal,runpy,sys;signal.alarm(int(sys.argv[1]));runpy.run_module('support_agent.providers',run_name='__main__')",
                    str(runtime["timeout_seconds"]),
                ],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=runtime["timeout_seconds"],
                check=False,
            )
        except subprocess.TimeoutExpired:
            # OS process termination bounds DNS, TLS and the whole response, not just individual reads.
            raise ProviderFailure("timeout", attempts=None) from None
        except OSError:
            raise ProviderFailure("network_error", attempts=0) from None
        if result.returncode < 0:
            raise ProviderFailure("timeout", attempts=None)
        try:
            value = json.loads(result.stdout)
            if result.returncode or not isinstance(value, dict):
                raise ValueError
            if "error_category" in value:
                raise ProviderFailure(
                    value["error_category"],
                    value["attempts"],
                    value.get("input_tokens"),
                    value.get("output_tokens"),
                )
            value["tool_calls"] = tuple(ModelToolCall(**c) for c in value.get("tool_calls", []))
            return Completion(**value)
        except (ValueError, TypeError):
            raise ProviderFailure("invalid_response", attempts=None) from None

    def complete_in_process(
        self, *, base_url, api_key, model, messages, runtime, tools=None, embedding_input=None
    ):
        validate_base_url(base_url, self.allowed_hosts)
        timeout = runtime["timeout_seconds"]
        payload = json.dumps(
            {
                "model": model,
                "messages": messages,
                **(
                    {"temperature": runtime["temperature"]}
                    if runtime.get("send_temperature", True)
                    else {}
                ),
                runtime.get("token_parameter", "max_tokens"): runtime["max_output_tokens"],
                "stream": False,
                **(
                    {"response_format": {"type": "json_object"}}
                    if tools is None
                    else {
                        **(
                            {"tools": tools, "tool_choice": "auto", "parallel_tool_calls": False}
                            if tools
                            else {}
                        ),
                    }
                ),
            },
            allow_nan=False,
        ).encode()
        if embedding_input is not None:
            payload = json.dumps(
                {
                    "model": model,
                    "input": embedding_input,
                    "dimensions": 1536,
                    "encoding_format": "float",
                },
                allow_nan=False,
            ).encode()
        deadline = time.monotonic() + timeout
        # TLS verification enabled, no proxies, redirects or environment config.
        with httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PublicNetworkBackend(self.private_hosts),
            retries=0,
            max_connections=1,
        ) as pool:
            for attempt in (1,):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderFailure("timeout", attempt - 1)
                try:
                    with pool.stream(
                        "POST",
                        base_url.rstrip("/")
                        + ("/embeddings" if embedding_input is not None else "/chat/completions"),
                        headers={
                            "Authorization": "Bearer " + api_key,
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                            "Accept-Encoding": "identity",
                        },
                        content=payload,
                        extensions={
                            "timeout": {
                                "connect": min(5, remaining),
                                "read": remaining,
                                "write": remaining,
                                "pool": remaining,
                            }
                        },
                    ) as response:
                        if response.status != 200:
                            error_body = b""
                            for part in response.iter_stream():
                                if time.monotonic() > deadline:
                                    raise ProviderFailure("timeout", attempt)
                                if len(error_body) + len(part) > 8192:
                                    break
                                error_body += part
                            category = normalize_status(response.status, error_body)
                            raise ProviderFailure(category, attempt)
                        parts = []
                        size = 0
                        for part in response.iter_stream():
                            size += len(part)
                            if size > 65536:
                                raise ProviderFailure("invalid_response", attempt)
                            if time.monotonic() > deadline:
                                raise ProviderFailure("timeout", attempt)
                            parts.append(part)
                        if embedding_input is not None:
                            return parse_embedding(b"".join(parts), attempt)
                        return parse_completion(
                            b"".join(parts), attempt, allow_tools=tools is not None
                        )
                except httpcore.TimeoutException:
                    # A request may have reached the provider. Never retry an unknown result.
                    raise ProviderFailure("timeout", attempt) from None
                except (httpcore.NetworkError, httpcore.ProtocolError):
                    raise ProviderFailure("network_error", attempt) from None


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read(262145))
        allowed_hosts = payload.pop("allowed_hosts")
        private_hosts = payload.pop("private_hosts", [])
        result = OpenAICompatibleProvider(
            allowed_hosts, private_hosts=private_hosts
        ).complete_in_process(**payload)
        print(json.dumps(asdict(result), ensure_ascii=False))
    except ProviderFailure as exc:
        print(
            json.dumps(
                {
                    "error_category": exc.category,
                    "attempts": exc.attempts,
                    "input_tokens": exc.input_tokens,
                    "output_tokens": exc.output_tokens,
                }
            )
        )
    except Exception:
        print(json.dumps({"error_category": "provider_internal_error", "attempts": None}))


if __name__ == "__main__":
    main()
