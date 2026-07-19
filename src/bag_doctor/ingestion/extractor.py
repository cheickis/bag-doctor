from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .detector import InputKind, detect_input

MAX_UPLOAD_BYTES = 512 * 1024 * 1024


class InputValidationError(ValueError):
    pass


@dataclass
class StagedInput:
    path: Path
    kind: InputKind
    original_filename: str
    metadata_available: bool
    split_file_count: int
    warnings: list[str]
    _temporary: tempfile.TemporaryDirectory

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._temporary.cleanup()


def _safe_member(member: zipfile.ZipInfo) -> None:
    name = member.filename
    target = Path(name)
    if target.is_absolute() or ".." in target.parts or "\x00" in name:
        raise InputValidationError("ZIP contains an unsafe path")
    if member.is_dir():
        return
    mode = member.external_attr >> 16
    if mode and (mode & 0o170000) == 0o120000:
        raise InputValidationError("ZIP symlinks are not allowed")


def _zip_stage(source: Path, root: Path) -> tuple[Path, InputKind, bool, int, list[str]]:
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        for member in members:
            _safe_member(member)
        if not members:
            raise InputValidationError("ZIP archive is empty")
        archive.extractall(root)
    metadata = list(root.rglob("metadata.yaml"))
    db3 = list(root.rglob("*.db3"))
    if not metadata or not db3:
        raise InputValidationError("ZIP must contain metadata.yaml and at least one .db3 file")
    roots = set()
    for item in metadata:
        roots.add(item.parent)
    for item in db3:
        candidates = [parent for parent in [item.parent, *item.parents] if (parent / "metadata.yaml").exists()]
        if not candidates:
            raise InputValidationError("ZIP contains a .db3 without an associated metadata.yaml")
        roots.add(candidates[0])
    if len(roots) != 1:
        raise InputValidationError("ZIP contains multiple unrelated ROS 2 bag roots")
    bag_root = next(iter(roots))
    files = list(bag_root.glob("*.db3"))
    if not files:
        raise InputValidationError("ZIP metadata.yaml has no associated .db3 files")
    return bag_root, InputKind.SQLITE_DIRECTORY, True, len(files), []


def stage_upload(source: Path, original_filename: str, max_bytes: int = MAX_UPLOAD_BYTES) -> StagedInput:
    source = Path(source)
    if source.stat().st_size > max_bytes:
        raise InputValidationError(f"Upload exceeds maximum size of {max_bytes // (1024 * 1024)} MiB")
    temporary = tempfile.TemporaryDirectory(prefix="bag-doctor-")
    root = Path(temporary.name)
    suffix = Path(original_filename).suffix.lower()
    try:
        if suffix == ".zip":
            path, kind, metadata, count, warnings = _zip_stage(source, root)
        elif suffix == ".mcap":
            path = root / source.name
            shutil.copy2(source, path)
            kind, metadata, count, warnings = InputKind.MCAP, False, 1, [
                "metadata.yaml was not provided; bag-level metadata is unavailable.",
            ]
        elif suffix == ".db3":
            path = root / source.name
            shutil.copy2(source, path)
            kind, metadata, count, warnings = InputKind.SQLITE_STANDALONE, False, 1, [
                "metadata.yaml was not provided; bag-level metadata is unavailable.",
            ]
        else:
            raise InputValidationError("Unsupported upload extension; use .mcap, .db3, or .zip")
        if detect_input(path) == InputKind.UNSUPPORTED:
            raise InputValidationError("Uploaded file is not a usable ROS 2 bag")
        return StagedInput(path, kind, Path(original_filename).name, metadata, count, warnings, temporary)
    except Exception:
        temporary.cleanup()
        raise
