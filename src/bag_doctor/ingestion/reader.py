"""Format-independent timestamp reader facade."""
from pathlib import Path
from collections.abc import Iterator
from rosbags.rosbag2 import Reader


class BagReader:
    def __init__(self, path: Path):
        self.path = Path(path)

    def __enter__(self):
        self.reader = Reader(self.path)
        self.reader.open()
        return self

    def __exit__(self, *args):
        self.reader.close()

    @property
    def connections(self):
        return self.reader.connections

    def messages(self) -> Iterator:
        return self.reader.messages()
