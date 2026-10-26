"""Dedicated container identity; no host account or Docker group is required."""

import os
import stat
import subprocess
from uuid import UUID

SIGNER_UID = 12008
SIGNER_GID = 12008
KEY_PATH = "/run/nexus-proof-key/signing.key"


def publish_claim_reader(directory_fd, file_fd=None):
    """Owner grants only the signer read/traverse ACLs, never write access.

    Uses already-open descriptors (no symlink race). Called only for shared
    execution claim files, never for keys or the rest of the runtime directory.
    """
    for fd, permission in [(directory_fd, "r-x"), (file_fd, "r--")]:
        if fd is None:
            continue
        if os.fstat(fd).st_uid != os.getuid():
            raise ValueError("CLAIM_OWNER_MISMATCH")
        subprocess.run(
            ["setfacl", "--modify", f"u:{SIGNER_UID}:{permission}", "--", f"/proc/self/fd/{fd}"],
            pass_fds=(fd,),
            check=True,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def prepare_claim_readers(directory, owner):
    """Publish only this installation's existing regular claim files at startup."""
    UUID(owner)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        publish_claim_reader(directory_fd)
        for name in os.listdir(directory_fd):
            if not name.startswith(owner + "-") or not name.endswith(".lock"):
                raise ValueError("UNEXPECTED_CLAIM_FILE")
            UUID(name[len(owner) + 1 : -5])
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("CLAIM_REGULAR_FILE_REQUIRED")
                publish_claim_reader(directory_fd, fd)
            finally:
                os.close(fd)
    finally:
        os.close(directory_fd)
