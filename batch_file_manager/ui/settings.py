from PySide6.QtCore import QSettings


def settings() -> QSettings:
    return QSettings("batch-file-manager", "BatchFileManager")
