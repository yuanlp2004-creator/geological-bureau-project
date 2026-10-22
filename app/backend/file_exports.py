"""Publish complete export files without replacing a competing writer's output."""
from pathlib import Path
import os
import tempfile


def publish_export(directory: Path, name: str, content: bytes, extension: str, strategy: str) -> Path:
    if strategy not in {'suffix', 'error', 'overwrite'}:
        raise ValueError('invalid same-name strategy')
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    handle, temporary = tempfile.mkstemp(prefix='.export-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if strategy == 'overwrite':
            os.replace(temporary, target)
            return target
        index = 1
        while True:
            candidate = target if index == 1 else target.with_name(f'{target.stem} ({index}){extension}')
            try:
                # Windows rename refuses an existing destination, including on
                # removable filesystems without hard links. POSIX rename would
                # overwrite, so use an exclusive hard link there instead.
                if os.name == 'nt':
                    os.rename(temporary, candidate)
                else:
                    os.link(temporary, candidate)
                return candidate
            except FileExistsError:
                if strategy == 'error':
                    raise
                index += 1
    finally:
        Path(temporary).unlink(missing_ok=True)
