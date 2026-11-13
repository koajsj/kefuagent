from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response

from support_agent.dependencies import Database, TenantContext
from support_agent.services import user_memory
from support_agent.user_memory_schemas import (
    ConsentInput,
    ConsentOut,
    MemoryInput,
    MemoryOut,
    MemoryUsageOut,
)

router = APIRouter(prefix="/user-memory", tags=["User memory"])
MemoryKey = Annotated[
    str, Path(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
]


@router.get("/consent", response_model=ConsentOut)
def get_consent(db: Database, context: TenantContext):
    return user_memory.get_consent(db, context)


@router.put("/consent", response_model=ConsentOut)
def set_consent(data: ConsentInput, request: Request, db: Database, context: TenantContext):
    return user_memory.set_consent(db, context, data.enabled, request)


@router.get("", response_model=list[MemoryOut])
def listing(db: Database, context: TenantContext):
    return user_memory.listing(db, context)


@router.post("/cleanup")
def cleanup(request: Request, db: Database, context: TenantContext):
    return user_memory.cleanup(db, context, request)


@router.get("/usage/{call_id}", response_model=MemoryUsageOut)
def usage(call_id: UUID, db: Database, context: TenantContext):
    return user_memory.usage(db, context, call_id)


@router.delete("", status_code=204)
def clear(request: Request, db: Database, context: TenantContext):
    user_memory.clear(db, context, request)
    return Response(status_code=204)


@router.put("/{key}", response_model=MemoryOut)
def save(key: MemoryKey, data: MemoryInput, request: Request, db: Database, context: TenantContext):
    return user_memory.save(db, context, key, data, request)


@router.delete("/{key}", status_code=204)
def remove(key: MemoryKey, request: Request, db: Database, context: TenantContext):
    user_memory.remove(db, context, key, request)
    return Response(status_code=204)
