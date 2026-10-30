"""Actual loopback HTTP fixture, with TLS/network substitution confined to this test."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def test_custom_provider_wire_contract_without_external_network(monkeypatch):
    import httpcore

    from support_agent import providers

    observed = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            observed.append(
                (
                    self.path,
                    self.headers.get("Authorization"),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            body = json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "local_call",
                                        "type": "function",
                                        "function": {
                                            "name": "text_metrics",
                                            "arguments": '{"text":"你好"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 5},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class LoopbackStream(httpcore.NetworkStream):
        def __init__(self, stream):
            self.stream = stream

        def read(self, max_bytes, timeout=None):
            return self.stream.read(max_bytes, timeout)

        def write(self, buffer, timeout=None):
            return self.stream.write(buffer, timeout)

        def close(self):
            self.stream.close()

        def get_extra_info(self, info):
            return self.stream.get_extra_info(info)

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            return self

    class LocalBackend(httpcore.SyncBackend):
        def connect_tcp(self, host, port, **kwargs):
            assert host == "thirdparty.example" and port == 443
            return LoopbackStream(super().connect_tcp("127.0.0.1", server.server_port, **kwargs))

    monkeypatch.setattr(providers, "PublicNetworkBackend", LocalBackend)
    try:
        result = providers.OpenAICompatibleProvider(["thirdparty.example"]).complete_in_process(
            base_url="https://thirdparty.example/custom/v1",
            api_key="thirdparty-format-synthetic",
            model="custom/model-42",
            messages=[{"role": "user", "content": "统计你好"}],
            runtime={
                "timeout_seconds": 2,
                "temperature": 0.2,
                "max_output_tokens": 17,
                "token_parameter": "max_completion_tokens",
                "send_temperature": False,
            },
            tools=[
                {
                    "type": "function",
                    "function": {"name": "text_metrics", "parameters": {"type": "object"}},
                }
            ],
        )
        assert (
            result.input_tokens == 12
            and result.output_tokens == 5
            and result.tool_calls[0].name == "text_metrics"
        )
        path, auth, payload = observed[0]
        assert (
            path == "/custom/v1/chat/completions" and auth == "Bearer thirdparty-format-synthetic"
        )
        assert payload["model"] == "custom/model-42" and payload["max_completion_tokens"] == 17
        assert "temperature" not in payload and payload["tool_choice"] == "auto"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
