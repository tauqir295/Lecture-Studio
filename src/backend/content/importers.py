"""Source importers: Markdown, plain text, code, DOCX and PPTX -> ContentDocument.

All importers are topic-neutral and offline. Images referenced by the source are
extracted into `assets_dir` so the slide builder can place them on slides.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional
try:  # hardened XML parsing for untrusted DOCX files
    from defusedxml import ElementTree as ET
except ImportError:  # stdlib fallback (expat in Python 3.13 mitigates entity expansion attacks)
    from xml.etree import ElementTree as ET

from src.backend.content.model import (BULLETS, CODE, HEADING, IMAGE, PARAGRAPH, QUOTE, TABLE, Block,
                                       ContentDocument, Section)

CODE_EXT = {
    ".py": "python", ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx", ".go": "go", ".rs": "rust", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cs": "csharp", ".swift": "swift", ".rb": "ruby", ".php": "php",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".ps1": "powershell", ".sql": "sql", ".yaml": "yaml",
    ".yml": "yaml", ".json": "json", ".xml": "xml", ".html": "html", ".css": "css", ".scala": "scala",
    ".r": "r", ".m": "matlab", ".lua": "lua", ".dart": "dart", ".gradle": "groovy", ".groovy": "groovy",
    ".tf": "terraform", ".toml": "toml", ".ini": "ini", ".cds": "cds", ".abap": "abap", ".dockerfile": "docker",
}
MARKDOWN_EXT = {".md", ".markdown", ".mdown"}
TEXT_EXT = {".txt", ".text", ".rst", ".adoc"}
SUPPORTED_EXT = {".pdf", ".pptx", ".docx"} | MARKDOWN_EXT | TEXT_EXT | set(CODE_EXT)


def detect_type(path: Path) -> str:
    ext = path.suffix.lower()
    if path.name.lower() == "dockerfile":
        return "code"
    if ext == ".pdf":
        return "pdf"
    if ext == ".pptx":
        return "pptx"
    if ext == ".docx":
        return "docx"
    if ext in MARKDOWN_EXT:
        return "markdown"
    if ext in TEXT_EXT:
        return "text"
    if ext in CODE_EXT:
        return "code"
    raise ValueError(f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXT))}")


def _read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_bytes().decode("utf-8", "replace")


def _new_section(doc: ContentDocument, title: str, level: int = 1, ref: str = "") -> Section:
    sec = Section(title=title.strip() or doc.title, level=level, source_ref=ref)
    doc.sections.append(sec)
    return sec


# ====================================================================== Markdown
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_BULLET = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_MD_IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)\s*$")
_MD_INLINE = [(re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"), (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
              (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"), (re.compile(r"(?<!\w)([*_])(.+?)\1(?!\w)"), r"\2"),
              (re.compile(r"`([^`]+)`"), r"\1")]


def _md_inline(t: str) -> str:
    for rx, rep in _MD_INLINE:
        t = rx.sub(rep, t)
    return t.strip()


def import_markdown(path: Path, assets_dir: Path) -> ContentDocument:
    text = _read_text(path)
    if text.startswith("---"):  # YAML front matter
        end = text.find("\n---", 3)
        if end > 0:
            text = text[end + 4:]
    lines = text.splitlines()
    doc = ContentDocument(title=path.stem.replace("_", " ").replace("-", " ").strip(), source_type="markdown",
                          source_path=path)
    sec: Optional[Section] = None
    para: List[str] = []
    i = 0
    first_h1 = True

    def cur() -> Section:
        nonlocal sec
        if sec is None:
            sec = _new_section(doc, doc.title, 1, "start")
        return sec

    def flush_para():
        if para:
            cur().blocks.append(Block(PARAGRAPH, _md_inline(" ".join(para))))
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        fence = re.match(r"^\s*(```+|~~~+)\s*([\w+#.-]*)", line)
        if fence:
            flush_para()
            marker, lang = fence.group(1), fence.group(2)
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker[:3]):
                body.append(lines[i])
                i += 1
            cur().blocks.append(Block(CODE, "\n".join(body).rstrip("\n"), language=lang.lower()))
            i += 1
            continue
        h = _MD_HEADING.match(stripped)
        if h:
            flush_para()
            level, title = len(h.group(1)), _md_inline(h.group(2))
            if level == 1 and first_h1 and not doc.sections:
                doc.title, first_h1 = title, False
                sec = _new_section(doc, title, 1, f"heading '{title}'")
            elif level <= 3:
                sec = _new_section(doc, title, level, f"heading '{title}'")
            else:
                cur().blocks.append(Block(HEADING, title, level=level))
            i += 1
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        img = _MD_IMAGE.match(stripped)
        if img:
            flush_para()
            p = (path.parent / img.group(2)).resolve()
            cur().blocks.append(Block(IMAGE, img.group(1), image_path=p if p.is_file() else None))
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush_para()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append([_md_inline(c) for c in cells])
                i += 1
            cur().blocks.append(Block(TABLE, rows=rows))
            continue
        b = _MD_BULLET.match(line)
        if b:
            flush_para()
            items, numbered = [], b.group(2)[0].isdigit()
            while i < len(lines):
                m = _MD_BULLET.match(lines[i])
                if m:
                    indent = "  " * (len(m.group(1)) // 2)
                    items.append(indent + _md_inline(m.group(3)))
                elif lines[i].strip() and lines[i].startswith(("  ", "\t")) and items:
                    items[-1] += " " + _md_inline(lines[i])
                else:
                    break
                i += 1
            cur().blocks.append(Block(BULLETS, items=items, numbered=numbered))
            continue
        if stripped.startswith(">"):
            flush_para()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            cur().blocks.append(Block(QUOTE, _md_inline(" ".join(quote))))
            continue
        para.append(stripped)
        i += 1
    flush_para()
    return doc


# ====================================================================== Plain text
def import_text(path: Path, assets_dir: Path) -> ContentDocument:
    text = _read_text(path)
    doc = ContentDocument(title=path.stem.replace("_", " ").strip(), source_type="text", source_path=path)
    sec = _new_section(doc, doc.title, 1, "start")
    blocks = re.split(r"\n\s*\n", text)
    for raw in blocks:
        lines = [l.rstrip() for l in raw.strip("\n").splitlines()]
        if not lines:
            continue
        first = lines[0].strip()
        underline = len(lines) >= 2 and re.fullmatch(r"[=\-~^]{3,}", lines[1].strip() or "x")
        is_heading = (len(lines) == 1 and len(first) < 70 and not first.endswith((".", ",", ";", ":"))
                      and (first.isupper() or re.match(r"^(\d+(\.\d+)*[.)]?\s+)\S", first))) or underline
        if is_heading:
            sec = _new_section(doc, first.title() if first.isupper() else first, 2, f"'{first}'")
            lines = lines[2:] if underline else []
            if not lines:
                continue
        if all(re.match(r"^\s*([-*•]|\d+[.)])\s+", l) for l in lines if l.strip()):
            sec.blocks.append(Block(BULLETS, items=[re.sub(r"^\s*([-*•]|\d+[.)])\s+", "", l) for l in lines if l.strip()]))
        elif all(l.startswith(("    ", "\t")) for l in lines if l.strip()):
            sec.blocks.append(Block(CODE, "\n".join(l[4:] if l.startswith("    ") else l[1:] for l in lines)))
        else:
            sec.blocks.append(Block(PARAGRAPH, " ".join(l.strip() for l in lines)))
    return doc


# ====================================================================== Code files
def import_code(path: Path, assets_dir: Path, max_lines: int = 14) -> ContentDocument:
    text = _read_text(path).expandtabs(4)
    lang = CODE_EXT.get(path.suffix.lower(), "docker" if path.name.lower() == "dockerfile" else "")
    doc = ContentDocument(title=path.name, source_type="code", source_path=path,
                          subtitle=f"{lang or 'Source'} walkthrough · {len(text.splitlines())} lines")
    lines = text.splitlines()
    start = 0
    while start < len(lines):
        end = min(start + max_lines, len(lines))
        if end < len(lines):  # prefer to cut at a blank line
            for j in range(end, start + max_lines // 2, -1):
                if not lines[j - 1].strip():
                    end = j
                    break
        chunk = lines[start:end]
        while chunk and not chunk[-1].strip():
            chunk.pop()
        if any(l.strip() for l in chunk):
            sec = _new_section(doc, f"{path.name} · lines {start + 1}–{start + len(chunk)}", 2,
                               f"lines {start + 1}–{start + len(chunk)}")
            sec.blocks.append(Block(CODE, "\n".join(chunk), language=lang))
            comments = [re.sub(r"^\s*(#|//|--|/\*+|\*)\s?", "", l).strip(" */") for l in chunk
                        if re.match(r"^\s*(#(?!!)|//|--|/\*|\*)", l)]
            if comments:
                sec.notes = " ".join(c for c in comments if c)
        start = end
        while start < len(lines) and not lines[start].strip():
            start += 1
    return doc


# ====================================================================== DOCX (no extra dependency)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _w_text(el) -> str:
    out = []
    for node in el.iter():
        if node.tag == _W + "t":
            out.append(node.text or "")
        elif node.tag == _W + "tab":
            out.append("    ")
        elif node.tag in (_W + "br", _W + "cr"):
            out.append("\n")
    return "".join(out)


def import_docx(path: Path, assets_dir: Path) -> ContentDocument:
    doc = ContentDocument(title=path.stem.replace("_", " "), source_type="docx", source_path=path)
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
        rels = {}
        if "word/_rels/document.xml.rels" in z.namelist():
            for r in ET.fromstring(z.read("word/_rels/document.xml.rels")).iter(_REL + "Relationship"):
                rels[r.get("Id")] = r.get("Target")
        try:
            core = ET.fromstring(z.read("docProps/core.xml"))
            t = core.find("{http://purl.org/dc/elements/1.1/}title")
            if t is not None and (t.text or "").strip():
                doc.title = t.text.strip()
        except KeyError:
            pass
        body = root.find(_W + "body")
        sec: Optional[Section] = None
        bullets: List[str] = []
        code: List[str] = []
        img_n = 0

        def cur():
            nonlocal sec
            if sec is None:
                sec = _new_section(doc, doc.title, 1, "start")
            return sec

        def flush():
            if bullets:
                cur().blocks.append(Block(BULLETS, items=list(bullets)))
                bullets.clear()
            if code:
                cur().blocks.append(Block(CODE, "\n".join(code)))
                code.clear()

        for el in list(body):
            if el.tag == _W + "tbl":
                flush()
                rows = [[_w_text(tc).strip() for tc in tr.findall(_W + "tc")] for tr in el.findall(_W + "tr")]
                if rows:
                    cur().blocks.append(Block(TABLE, rows=rows))
                continue
            if el.tag != _W + "p":
                continue
            ppr = el.find(_W + "pPr")
            style = ""
            if ppr is not None and ppr.find(_W + "pStyle") is not None:
                style = ppr.find(_W + "pStyle").get(_W + "val", "")
            text = _w_text(el)
            sl = style.lower()
            # images in this paragraph
            for blip in el.iter(_A + "blip"):
                target = rels.get(blip.get(_R + "embed"))
                if target:
                    member = "word/" + target.lstrip("/") if not target.startswith("word/") else target
                    if member in z.namelist():
                        img_n += 1
                        assets_dir.mkdir(parents=True, exist_ok=True)
                        out = assets_dir / f"docx_image_{img_n:03d}{Path(member).suffix.lower()}"
                        out.write_bytes(z.read(member))
                        flush()
                        cur().blocks.append(Block(IMAGE, text.strip(), image_path=out))
            if sl == "title":
                doc.title = text.strip() or doc.title
                continue
            if sl.startswith("subtitle"):
                doc.subtitle = text.strip()
                continue
            m = re.match(r"heading\s*(\d)", sl.replace("berschrift", "heading"))
            if m and text.strip():
                flush()
                lvl = int(m.group(1))
                if lvl <= 3:
                    sec = _new_section(doc, text.strip(), lvl, f"heading '{text.strip()}'")
                else:
                    cur().blocks.append(Block(HEADING, text.strip(), level=lvl))
                continue
            is_list = (ppr is not None and ppr.find(_W + "numPr") is not None) or "list" in sl
            is_code = any(k in sl for k in ("code", "preformatted", "source", "macro"))
            if is_code:
                if bullets:
                    cur().blocks.append(Block(BULLETS, items=list(bullets))); bullets.clear()
                code.append(text)
                continue
            if not text.strip():
                flush()
                continue
            if is_list:
                if code:
                    cur().blocks.append(Block(CODE, "\n".join(code))); code.clear()
                bullets.append(text.strip())
                continue
            flush()
            kind = QUOTE if "quote" in sl else PARAGRAPH
            cur().blocks.append(Block(kind, text.strip()))
        flush()
    return doc


# ====================================================================== PPTX
def import_pptx(path: Path, assets_dir: Path) -> ContentDocument:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(path))
    doc = ContentDocument(title=path.stem.replace("_", " "), source_type="pptx", source_path=path)
    if prs.core_properties.title:
        doc.title = prs.core_properties.title
    img_n = 0

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from walk(sh.shapes)
            else:
                yield sh

    for idx, slide in enumerate(prs.slides, 1):
        title_shape = slide.shapes.title
        title = (title_shape.text_frame.text.strip() if title_shape is not None and title_shape.has_text_frame
                 else "") or f"Slide {idx}"
        sec = _new_section(doc, title, 2, f"slide {idx}")
        for sh in walk(slide.shapes):
            if title_shape is not None and sh.shape_id == title_shape.shape_id:
                continue
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                img_n += 1
                assets_dir.mkdir(parents=True, exist_ok=True)
                out = assets_dir / f"pptx_image_{img_n:03d}.{sh.image.ext}"
                out.write_bytes(sh.image.blob)
                sec.blocks.append(Block(IMAGE, sh.name if not sh.name.lower().startswith("picture") else "",
                                        image_path=out))
            elif getattr(sh, "has_table", False) and sh.has_table:
                rows = [[c.text.strip() for c in r.cells] for r in sh.table.rows]
                sec.blocks.append(Block(TABLE, rows=rows))
            elif sh.has_text_frame:
                items = []
                for p in sh.text_frame.paragraphs:
                    t = "".join(r.text for r in p.runs).strip()
                    if t:
                        items.append("  " * p.level + t)
                if len(items) == 1 and len(items[0]) > 120:
                    sec.blocks.append(Block(PARAGRAPH, items[0]))
                elif items:
                    sec.blocks.append(Block(BULLETS, items=items))
        if slide.has_notes_slide:
            sec.notes = slide.notes_slide.notes_text_frame.text.strip()
    return doc


IMPORTERS: Dict[str, Callable[[Path, Path], ContentDocument]] = {
    "markdown": import_markdown, "text": import_text, "code": import_code,
    "docx": import_docx, "pptx": import_pptx,
}


def import_document(path: Path, assets_dir: Path) -> ContentDocument:
    kind = detect_type(path)
    if kind == "pdf":
        raise ValueError("PDF files are imported directly (no conversion needed).")
    return IMPORTERS[kind](Path(path), Path(assets_dir))
