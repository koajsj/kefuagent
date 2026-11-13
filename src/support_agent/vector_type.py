"""Minimal pgvector binding; values stay bound parameters, never interpolated SQL."""

import json
import math

from sqlalchemy.types import UserDefinedType

DIMENSIONS = 1536


class Vector(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw):
        return f"VECTOR({DIMENSIONS})"

    def bind_processor(self, dialect):
        def encode(value):
            if (
                len(value) != DIMENSIONS
                or any(not math.isfinite(v) for v in value)
                or not any(value)
            ):
                raise ValueError("Embedding must be a finite nonzero 1536-dimensional vector")
            return json.dumps(value, allow_nan=False, separators=(",", ":"))

        return encode

    def result_processor(self, dialect, coltype):
        return lambda value: json.loads(value) if isinstance(value, str) else value
