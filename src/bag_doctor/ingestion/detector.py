from enum import StrEnum
from pathlib import Path


class InputKind(StrEnum):
    MCAP = "ros2_mcap"
    SQLITE_DIRECTORY = "ros2_sqlite_directory"
    SQLITE_STANDALONE = "ros2_sqlite_standalone"
    UNSUPPORTED = "unsupported"


def detect_input(path: Path) -> InputKind:
    path = Path(path)
    if path.is_file() and path.suffix.lower() == ".mcap":
        return InputKind.MCAP
    if path.is_file() and path.suffix.lower() == ".db3":
        return InputKind.SQLITE_STANDALONE
    if path.is_dir() and any(path.glob("*.mcap")):
        return InputKind.MCAP
    if path.is_dir() and (path / "metadata.yaml").is_file() and any(path.glob("*.db3")):
        return InputKind.SQLITE_DIRECTORY
    return InputKind.UNSUPPORTED
