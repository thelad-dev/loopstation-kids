"""Draw the app icon (a small 4 x 3 pad grid) and save it as a Windows .ico file.

Usage: python packaging/windows/make_icon.py <out.ico>

The icon is drawn with Qt at every size, so no binary image lives in the
repository. The .ico file holds one PNG per size, which Windows Vista and
newer read directly.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

SIZES = (16, 24, 32, 48, 64, 128, 256)
# Pad colours from loopstation.gui.widgets, row by row.
GRID = (
    ("#FFD60A", "#32D74B", "#F2F2F2", "#FFD60A"),
    ("#F2F2F2", "#FF3B30", "#FFD60A", "#32D74B"),
    ("#32D74B", "#FFD60A", "#F2F2F2", "#F2F2F2"),
)
BACKGROUND = "#0E0E10"


def render_png(size: int) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(BACKGROUND))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.18, size * 0.18)

    rows, cols = len(GRID), len(GRID[0])
    margin = size * 0.12
    gap = max(1.0, size * 0.045)
    cell_w = (size - 2 * margin - (cols - 1) * gap) / cols
    cell_h = (size - 2 * margin - (rows - 1) * gap) / rows
    top = margin + (size - 2 * margin - rows * cell_h - (rows - 1) * gap) / 2
    for r, row in enumerate(GRID):
        for c, color in enumerate(row):
            painter.setBrush(QColor(color))
            rect = QRectF(margin + c * (cell_w + gap), top + r * (cell_h + gap), cell_w, cell_h)
            radius = min(cell_w, cell_h) * 0.22
            painter.drawRoundedRect(rect, radius, radius)
    painter.end()

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError(f"cannot encode {size}px icon as PNG")
    buffer.close()
    return bytes(data.data())


def build_ico(images: dict[int, bytes]) -> bytes:
    """ICO container with PNG payloads (ICONDIR, ICONDIRENTRY per image, data)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, png in sorted(images.items()):
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(payload))
        payload += png
    return header + entries + payload


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    _app = QGuiApplication.instance() or QGuiApplication([])
    out = Path(argv[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_ico({size: render_png(size) for size in SIZES}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
