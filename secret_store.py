"""Cross-platform, fail-closed persistence for the signing secret."""
import os
from pathlib import Path
import secrets
import tempfile


def load_jwt_secret(path: Path, environ=None) -> str:
    environ = os.environ if environ is None else environ
    supplied = environ.get("JWT_SECRET", "").strip()
    if supplied and supplied != "generate-random-secret-on-startup":
        if len(supplied.encode("utf-8")) < 32:
            raise RuntimeError("JWT_SECRET must contain at least 32 bytes")
        return supplied

    def read_existing():
        if path.is_symlink():
            raise RuntimeError("JWT secret file must not be a symbolic link")
        value = path.read_text(encoding="utf-8").strip()
        if len(value.encode("utf-8")) < 32:
            raise RuntimeError("JWT secret file is invalid; restore it securely")
        if os.name != "nt":
            path.chmod(0o600)
        return value

    try:
        return read_existing()
    except FileNotFoundError:
        pass

    # Publish a fully written file without replacing another process's winner.
    # Hard links are supported on Windows NTFS and ordinary POSIX filesystems.
    # Unsupported filesystems fail closed rather than creating an ephemeral key.
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".jwt_secret-", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(64))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
        return read_existing()
    except OSError:
        raise RuntimeError("Unable to persist JWT secret; configure JWT_SECRET securely") from None
    finally:
        if temporary is not None:
            os.unlink(temporary)
