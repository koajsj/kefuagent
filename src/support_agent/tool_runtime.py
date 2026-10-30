"""Deployment-owned capabilities. No handler, module or address comes from database/model input."""

import json
import os
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from threading import BoundedSemaphore, Event, Thread
from types import MappingProxyType

import psutil

from support_agent.tool_protocol import ExecutionContext, check_schema

TEXT_PARAMETERS = {
    "type": "object",
    "properties": {"text": {"type": "string", "maxLength": 4000}},
    "required": ["text"],
    "additionalProperties": False,
}
TEXT_OUTPUT = {
    "type": "object",
    "properties": {"characters": {"type": "integer"}, "words": {"type": "integer"}},
    "required": ["characters", "words"],
    "additionalProperties": False,
}


def text_metrics(arguments: dict, context: ExecutionContext) -> dict:
    text = arguments["text"]
    return {"characters": len(text), "words": len(text.split())}


@dataclass(frozen=True)
class Capability:
    key: str
    version: int
    parameters: dict
    output_schema: dict
    handler: Callable
    read_only: bool = True
    timeout_seconds: float = 2

    def __post_init__(self):
        check_schema(self.parameters)
        check_schema(self.output_schema)
        if not 0 < self.timeout_seconds <= 5 or "<locals>" in self.handler.__qualname__:
            raise ValueError("Use a deployment-owned module-level handler with timeout <= 5s")


class ToolRegistry:
    def __init__(self, capabilities):
        items = {(c.key, c.version): c for c in capabilities}
        if len(items) != len(capabilities):
            raise ValueError("Duplicate deployment capability")
        self.items = MappingProxyType(items)

    def get(self, key, version):
        return self.items.get((key, version))


def default_registry():
    return ToolRegistry([Capability("text_metrics", 1, TEXT_PARAMETERS, TEXT_OUTPUT, text_metrics)])


class ToolFailure(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


_TOOL_SLOTS = BoundedSemaphore(4)


class ProcessToolRunner:
    def run(self, capability, arguments, context):
        if not _TOOL_SLOTS.acquire(blocking=False):
            raise ToolFailure("tool_busy")
        stop = Event()
        exceeded = Event()
        watcher = None
        try:
            payload = json.dumps(
                {
                    "module": capability.handler.__module__,
                    "function": capability.handler.__qualname__,
                    "arguments": arguments,
                    "context": asdict(context),
                },
                default=str,
                allow_nan=False,
            ).encode()
            # Only code paths are inherited; no DB URL, API key, master key or caller environment.
            env = {
                "PATH": os.defpath,
                "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            with (
                tempfile.TemporaryDirectory(prefix="support-tool-") as workdir,
                tempfile.TemporaryFile() as output,
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        "import signal,runpy;signal.alarm(6);runpy.run_module('support_agent.tool_worker',run_name='__main__')",
                    ],
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                    cwd=workdir,
                ) as process,
            ):

                def kill_group():
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

                def monitor():
                    try:
                        child = psutil.Process(process.pid)
                        while not stop.is_set():
                            if child.memory_info().rss > 256 * 1024 * 1024:
                                exceeded.set()
                                kill_group()
                                return
                            stop.wait(0.02)
                    except psutil.NoSuchProcess:
                        return
                    except psutil.Error:
                        exceeded.set()
                        kill_group()

                watcher = Thread(target=monitor, daemon=True)
                watcher.start()
                try:
                    process.communicate(payload, timeout=capability.timeout_seconds)
                except subprocess.TimeoutExpired:
                    kill_group()
                    process.wait(timeout=1)
                    raise ToolFailure("tool_timeout") from None
                finally:
                    kill_group()
                output.seek(0)
                stdout = output.read(8193)
                if exceeded.is_set():
                    raise ToolFailure("tool_resource_limit")
                if process.returncode or len(stdout) > 8192:
                    raise ToolFailure("tool_process_interrupted")
                value = json.loads(stdout)
                if "error" in value:
                    raise ToolFailure(value["error"])
                return value["data"]
        except (OSError, ValueError, KeyError, TypeError):
            raise ToolFailure("tool_internal_error") from None
        finally:
            stop.set()
            if watcher:
                watcher.join(timeout=1)
            _TOOL_SLOTS.release()
