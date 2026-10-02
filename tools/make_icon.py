"""Regenerate batch_file_manager/assets/icon.ico from the SVG sources. Run by hand after editing them.

Qt's ICO writer only emits a single image, which Windows then squashes for the 16px taskbar slot.
The ICO container is a 6-byte header plus one 16-byte directory entry per PNG, so build it here.
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

# 16px uses a lettering-free variant; lettering smears into noise at that size.
SIZES = {16: "icon-16.svg", 32: "icon.svg", 48: "icon.svg", 256: "icon.svg"}
ASSETS = Path(__file__).resolve().parent.parent / "batch_file_manager" / "assets"


def render_png(source: str, size: int) -> bytes:
    renderer = QSvgRenderer(str(ASSETS / source))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def main() -> None:
    QGuiApplication(sys.argv)  # QImage/QPainter need a Qt application object
    pngs = [render_png(source, size) for size, source in SIZES.items()]

    offset = 6 + 16 * len(pngs)
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries, payload = b"", b""
    for size, png in zip(SIZES, pngs):
        # 0 in the width/height byte means 256; colour count and planes stay 0/1 for PNG entries.
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        payload += png

    out = ASSETS / "icon.ico"
    out.write_bytes(header + entries + payload)
    print(f"wrote {out} ({out.stat().st_size} bytes, sizes {', '.join(map(str, SIZES))})")


if __name__ == "__main__":
    main()
