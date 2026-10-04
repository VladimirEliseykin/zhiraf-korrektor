"""Plain text: one line is one paragraph; encoding and line endings are kept on saving."""
from .model import Document, Paragraph, SaveReport, Span, apply_replacements, group_by_paragraph

BOM = b"\xef\xbb\xbf"


def read_txt(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(BOM):
        encoding = "utf-8-sig"
    else:
        try:
            raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = "cp1251"
    text = raw.decode(encoding, "replace")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    doc = Document([Paragraph([Span(line)]) for line in lines], kind="txt", path=path, editable=False, saved_as="txt")
    doc.source = {"encoding": encoding, "newline": newline}
    return doc


def save_txt(doc, replacements, dst):
    groups = group_by_paragraph(replacements)
    lines = [apply_replacements(p.text, groups.get(i, [])) for i, p in enumerate(doc.paragraphs)]
    with open(dst, "w", encoding=doc.source["encoding"], newline="") as f:
        f.write(doc.source["newline"].join(lines))
    return SaveReport(dst, len(replacements))
