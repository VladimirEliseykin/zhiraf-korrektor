"""Build the multi-size .ico from the logo (host only)."""
import struct

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _png_bytes(image):
    from PySide2.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    if not image.save(buf, "PNG"):
        raise RuntimeError("cannot encode PNG")
    buf.close()
    return bytes(data)


def make_icon(png, ico):
    """Write `ico` with one PNG-encoded image per size.

    Qt's own ico writer stores a single image per file, so the container is
    written here. PNG entries are valid from Windows Vista on.
    """
    from PySide2.QtCore import Qt
    from PySide2.QtGui import QImage
    src = QImage(png)
    if src.isNull():
        raise RuntimeError("cannot read %s" % png)
    src = src.convertToFormat(QImage.Format_ARGB32)
    blobs = []
    for size in SIZES:
        scaled = src.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        blobs.append(_png_bytes(scaled))
    head = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries = b""
    for size, blob in zip(SIZES, blobs):
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    with open(ico, "wb") as f:
        f.write(head + entries + b"".join(blobs))
