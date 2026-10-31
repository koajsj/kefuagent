"""Local storage addressed exclusively by validated server UUIDs, never supplied paths."""

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
            # Exclusive creation has no temporary orphan lifecycle and is safe to repeat by digest.
            name = str(UUID(str(document_id)))
            try:
                out = os.open(
                    name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
                )
            except FileExistsError:
                if self.read(tenant_id, document_id) != content:
                    raise OSError("Existing storage content differs") from None
                return
            try:
                with os.fdopen(out, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                os.unlink(name, dir_fd=fd)
                raise
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
            try:
                os.unlink(str(UUID(str(document_id))), dir_fd=fd)
            except FileNotFoundError:
                pass
        finally:
            os.close(fd)

    def exists(self, tenant_id, document_id):
        try:
            self.read(tenant_id, document_id)
            return True
        except FileNotFoundError:
            return False
