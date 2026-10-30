"""Private subprocess entry; imported targets are supplied only by the static deployment registry."""

import contextlib
import importlib
import json
import logging
import os
import resource
import signal
import sys
from uuid import UUID

from support_agent.tool_protocol import ExecutionContext


def main():
    signal.alarm(6)
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8192, 8192))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    logging.disable(logging.CRITICAL)
    try:
        payload = json.loads(sys.stdin.buffer.read(65537))
        # Prints from trusted handlers/imports cannot become protocol output or application logs.
        with (
            open(os.devnull, "w") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            handler = importlib.import_module(payload["module"])
            for part in payload["function"].split("."):
                handler = getattr(handler, part)
            ctx = {
                k: UUID(v) if k.endswith("_id") and v is not None and k != "tool_call_id" else v
                for k, v in payload["context"].items()
            }
            data = handler(payload["arguments"], ExecutionContext(**ctx))
            encoded = json.dumps({"data": data}, allow_nan=False)
            if not isinstance(data, dict) or len(encoded.encode()) > 8192:
                raise ValueError
        sys.stdout.write(encoded)
    except Exception:
        sys.stdout.write('{"error":"tool_handler_error"}')


if __name__ == "__main__":
    main()
