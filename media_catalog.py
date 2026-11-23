"""Small, shared folder index: never decode thousands of images just to list them."""
import os
from pathlib import Path
from PySide6.QtGui import QImageReader


class MediaCatalog:
    def __init__(self):
        self.extensions = {'.' + bytes(fmt).decode().lower() for fmt in QImageReader.supportedImageFormats()}
        self._cache = {}

    def files(self, folder):
        folder = str(Path(folder).expanduser().resolve())
        try:
            stat = os.stat(folder)
            stamp = (stat.st_dev, stat.st_ino, stat.st_mtime_ns)
            cached = self._cache.get(folder)
            if cached and cached[0] == stamp:
                return list(cached[1])
            with os.scandir(folder) as entries:
                files = sorted((entry.path for entry in entries
                    if Path(entry.name).suffix.lower() in self.extensions and entry.is_file()), key=str.casefold)
            # Bound memory when switching between many different folders.
            if len(self._cache) >= 8:
                self._cache.pop(next(iter(self._cache)))
            self._cache[folder] = (stamp, tuple(files))
            return files
        except OSError:
            return []

    @staticmethod
    def readable(path):
        return QImageReader(path).canRead()
