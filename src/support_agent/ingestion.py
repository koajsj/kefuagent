"""Synchronous, disposable parser process; raw files never become executable code."""

import io
import json
import logging
import os
import re
import resource
import signal
import subprocess
import sys
import zipfile
from pathlib import PurePath
from threading import BoundedSemaphore, Event, Thread

import psutil

from support_agent.errors import AppError

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 500000
MIMES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def validate_upload(filename, content):
    if (
        not filename
        or len(filename) > 200
        or any(c in filename for c in "/\\")
        or any(ord(c) < 32 for c in filename)
    ):
        raise AppError(422, "invalid_document", "Use a simple filename with a supported extension")
    suffix = PurePath(filename).suffix.lower()
    if suffix not in MIMES or not content or len(content) > MAX_FILE_BYTES:
        raise AppError(
            422, "invalid_document", "Unsupported document type, empty file or size exceeds 5 MiB"
        )
    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise AppError(422, "invalid_document", "PDF signature does not match filename")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                entries = z.infolist()
                if (
                    len(entries) > 1000
                    or sum(i.file_size for i in entries) > 20 * 1024 * 1024
                    or any(i.flag_bits & 1 or i.file_size > 8 * 1024 * 1024 for i in entries)
                    or len({i.filename for i in entries}) != len(entries)
                    or not {"[Content_Types].xml", "word/document.xml"}.issubset(z.namelist())
                    or any(i.filename.lower().endswith("vbaproject.bin") for i in entries)
                ):
                    raise ValueError
        except (ValueError, zipfile.BadZipFile):
            raise AppError(
                422, "invalid_document", "Invalid DOCX package or resource limits exceeded"
            ) from None
    if suffix in (".txt", ".md"):
        try:
            value = content.decode("utf-8-sig")
            if "\x00" in value or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
                raise ValueError
        except (UnicodeError, ValueError):
            raise AppError(
                422, "invalid_document", "Text documents must be UTF-8 without binary control bytes"
            ) from None
    return suffix, MIMES[suffix]


def chunk_sections(sections):
    chunks = []
    grouped = []
    for text, page, section in sections:
        if grouped and grouped[-1][1:] == (page, section):
            previous = grouped[-1][0]
            grouped[-1] = (previous + "\n\n" + text, page, section)
        else:
            grouped.append((text, page, section))
    for text, page, section in grouped:
        text = text.replace("\r\n", "\n").replace("\x00", "").strip()
        for start in range(0, len(text), 1000):
            item = text[start : start + 1200].strip()
            if item:
                chunks.append({"content": item, "page": page, "section": section})
            if start + 1200 >= len(text):
                break
    if not chunks or len(chunks) > 750:
        raise ValueError("empty_or_large")
    return chunks


def parse_file(content, suffix):
    sections = []
    if suffix == ".pdf":
        from pypdf import PdfReader, filters

        filters.ZLIB_MAX_OUTPUT_LENGTH = 8 * 1024 * 1024
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError("pdf_limits")
        total = 0
        for n, page in enumerate(reader.pages, 1):
            stream = page.get_contents()
            if stream is not None and len(stream.get_data()) > 8 * 1024 * 1024:
                raise ValueError("pdf_limits")
            body = page.extract_text() or ""
            total += len(body)
            if total > MAX_TEXT_CHARS:
                raise ValueError("text_limits")
            sections.append((body, n, None))
    elif suffix == ".docx":
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        doc = Document(io.BytesIO(content))
        heading = None
        total = 0
        for block in doc.iter_inner_content():
            if isinstance(block, Paragraph):
                body = block.text
                if block.style and block.style.name.startswith("Heading"):
                    heading = body[:200]
            elif isinstance(block, Table):
                body = "\n".join(" | ".join(cell.text for cell in row.cells) for row in block.rows)
            total += len(body)
            if total > MAX_TEXT_CHARS:
                raise ValueError("text_limits")
            sections.append((body, None, heading))
    else:
        body = content.decode("utf-8-sig")
        if len(body) > MAX_TEXT_CHARS:
            raise ValueError("text_limits")
        heading = None
        lines = []
        in_fence = False
        for line in body.splitlines():
            if suffix == ".md" and line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
            match = re.match(r"^#{1,6}\s+(.+)", line) if suffix == ".md" and not in_fence else None
            if match:
                sections.append(("\n".join(lines), None, heading))
                lines = []
                heading = match[1][:200]
            lines.append(line)
        sections.append(("\n".join(lines), None, heading))
    return chunk_sections(sections)


_PARSER_SLOTS = BoundedSemaphore(4)


def process_document(content, suffix):
    if not _PARSER_SLOTS.acquire(blocking=False):
        return None, "parse_busy"
    stop = Event()
    resource_failed = Event()
    watcher = None
    try:
        with subprocess.Popen(
            [sys.executable, "-m", "support_agent.ingestion", suffix],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
        ) as process:

            def watch_memory():
                try:
                    child = psutil.Process(process.pid)
                    while not stop.is_set():
                        if child.memory_info().rss > 512 * 1024 * 1024:
                            resource_failed.set()
                            process.kill()
                            return
                        stop.wait(0.05)
                except psutil.NoSuchProcess:
                    return
                except psutil.Error:
                    resource_failed.set()
                    process.kill()

            watcher = Thread(target=watch_memory, daemon=True)
            watcher.start()
            try:
                stdout, _ = process.communicate(content, timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                return None, "parse_timeout"
            if resource_failed.is_set():
                return None, "parse_resource_limit"
            if process.returncode:
                return None, "parse_failed"
            return json.loads(stdout), None
    except (ValueError, OSError):
        return None, "parse_unavailable"
    finally:
        stop.set()
        if watcher:
            watcher.join(timeout=1)
        _PARSER_SLOTS.release()


def main():
    # Limits are set inside the child, never preexec_fn in a threaded ASGI server.
    signal.alarm(15)
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    logging.disable(logging.CRITICAL)
    try:
        content = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            return 1
        chunks = parse_file(content, sys.argv[1])
        sys.stdout.write(json.dumps(chunks, ensure_ascii=False))
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
