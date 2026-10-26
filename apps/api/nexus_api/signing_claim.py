"""A signer takes the same fences using a READ-ONLY claim mount."""

import fcntl
import os
import stat
from uuid import UUID

from nexus_api.recovery import ExecutionClaim


class SigningClaim(ExecutionClaim):
    def __init__(self, engine, eid, owner, lock_dir, runtime_uid):
        UUID(str(owner))
        UUID(str(eid))
        super().__init__(engine, eid)
        self.directory, self.owner, self.runtime_uid = lock_dir, owner, runtime_uid

    def __enter__(self):
        super().__enter__()
        if not self.acquired:
            return self
        try:
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                if os.fstat(directory_fd).st_uid != self.runtime_uid:
                    raise ValueError("CLAIM_DIRECTORY_OWNER_MISMATCH")
                try:
                    fd = os.open(
                        f"{self.owner}-{self.eid}.lock",
                        os.O_RDONLY | os.O_NOFOLLOW,
                        dir_fd=directory_fd,
                    )
                except FileNotFoundError:
                    # DB fence is held. A new Docker owner cannot acquire it;
                    # any abandoned existing owner must have a retained file.
                    return self
            finally:
                os.close(directory_fd)
            meta = os.fstat(fd)
            if (
                not stat.S_ISREG(meta.st_mode)
                or meta.st_uid != self.runtime_uid
                or meta.st_nlink != 1
            ):
                os.close(fd)
                raise ValueError("CLAIM_FILE_OWNER_MISMATCH")
            self.file = os.fdopen(fd, "r")
            try:
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.close()
            return self
        except Exception:
            self.close()
            raise
