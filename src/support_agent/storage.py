"""Local storage addressed exclusively by validated server UUIDs, never supplied paths."""

import fcntl
import os
from pathlib import Path
from uuid import UUID


class LocalDocumentStorage:
    def __init__(self, root):
        self.root = Path(root).absolute()

    def _directory(self, tenant_id):
        # Deployment owns the root and its ancestors; refuse symlink substitution at each open.
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            name = str(UUID(str(tenant_id)))
            try:
                os.mkdir(name, mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
            return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        finally:
            os.close(root_fd)

    def write(self, tenant_id, document_id, content):
        fd = self._directory(tenant_id)
        try:
            # Serialize publishers/recovery, including a process killed mid-write.
            # The deterministic pending path belongs to the same committed UUID row.
            fcntl.flock(fd, fcntl.LOCK_EX)
            name = str(UUID(str(document_id)))
            pending = f".{name}.pending"
            try:
                existing = self.read(tenant_id, document_id)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if existing != content:
                    raise OSError("Existing storage content differs") from None
                try:
                    os.unlink(pending, dir_fd=fd)
                except FileNotFoundError:
                    pass
                os.fsync(fd)
                return
            out = os.open(
                pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
            try:
                with os.fdopen(out, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Hard-link publication cannot overwrite an existing final object.
                os.link(pending, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            finally:
                os.unlink(pending, dir_fd=fd)
                os.fsync(fd)
        finally:
            os.close(fd)

    def read(self, tenant_id, document_id):
        fd = self._directory(tenant_id)
        try:
            f = os.open(str(UUID(str(document_id))), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(f, "rb") as stream:
                content = stream.read(5242881)
                if len(content) > 5242880:
                    raise OSError("Storage size exceeded")
                return content
        finally:
            os.close(fd)

    def delete(self, tenant_id, document_id):
        fd = self._directory(tenant_id)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            name = str(UUID(str(document_id)))
            for owned in (name, f".{name}.pending"):
                try:
                    os.unlink(owned, dir_fd=fd)
                except FileNotFoundError:
                    pass
            os.fsync(fd)
        finally:
            os.close(fd)

    def exists(self, tenant_id, document_id):
        try:
            self.read(tenant_id, document_id)
            return True
        except FileNotFoundError:
            return False


def document_storage(settings):
    if settings.document_storage_backend == "s3":
        from support_agent.s3_storage import S3DocumentStorage

        return S3DocumentStorage(settings)
    return LocalDocumentStorage(settings.document_storage_root)
