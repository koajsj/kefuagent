from datetime import datetime
from uuid import UUID

from pydantic import Field

from support_agent.schemas import Input, Output


class ChunkMutation(Input):
    expected_current_id: UUID
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class ChunkEdit(ChunkMutation):
    content: str = Field(min_length=1, max_length=1200, pattern=r"\S")


class ChunkRestore(ChunkMutation):
    source_version_id: UUID


class ChunkVersion(Output):
    id: UUID
    document_id: UUID
    root_chunk_id: UUID
    position: int
    generation: int
    revision: int
    is_current: bool
    is_deleted: bool
    content: str
    page: int | None
    section: str | None
    revised_by: UUID | None
    revision_reason: str | None
    created_at: datetime
