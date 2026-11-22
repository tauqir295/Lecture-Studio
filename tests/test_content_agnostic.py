"""Format- and topic-agnostic import: Markdown, text, code, DOCX, PPTX -> slides -> project."""
import re
import zipfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.backend.content.importers import SUPPORTED_EXT, detect_type, import_document
from src.backend.content.model import BULLETS, CODE, IMAGE, PARAGRAPH, TABLE
from src.backend.content.pipeline import convert_source
from src.backend.content.profiles import GENERIC, detect_profile, load_profiles
from src.backend.content.slide_builder import MAX_BULLETS, MAX_CODE_LINES, build_slides

SAMPLES = Path("docs/samples")


def _pdf_pages(pdf: Path) -> int:
    import pypdf
    return len(pypdf.PdfReader(str(pdf)).pages)


def _page_size(pdf: Path):
    import pypdf
    box = pypdf.PdfReader(str(pdf)).pages[0].mediabox
    return float(box.width), float(box.height)


# ------------------------------------------------------------------ detection
@pytest.mark.parametrize("name,kind", [("a.pdf", "pdf"), ("a.pptx", "pptx"), ("a.docx", "docx"), ("a.md", "markdown"),
                                       ("a.txt", "text"), ("a.py", "code"), ("a.kt", "code"), ("Dockerfile", "code")])
def test_detect_type(name, kind):
    assert detect_type(Path(name)) == kind


def test_unsupported_type():
    with pytest.raises(ValueError):
        detect_type(Path("a.xyz"))


# ------------------------------------------------------------------ importers
def test_markdown_structure(tmp_path):
    doc = import_document(SAMPLES / "Linux_File_Permissions.md", tmp_path)
    assert doc.title == "Linux File Permissions"
    kinds = {b.kind for s in doc.sections for b in s.blocks}
    assert {PARAGRAPH, CODE, BULLETS, TABLE} <= kinds
    code = [b for s in doc.sections for b in s.blocks if b.kind == CODE]
    assert code[0].language == "bash" and "chmod 750" in code[1].text   # code preserved verbatim
    assert "`" not in doc.all_text().replace("```", "")                  # inline markup removed


def test_code_file_chunks_and_comments(tmp_path):
    doc = import_document(SAMPLES / "CounterViewModel.kt", tmp_path)
    total = sum(len(b.text.splitlines()) for s in doc.sections for b in s.blocks)
    src_nonblank = [l for l in (SAMPLES / "CounterViewModel.kt").read_text().splitlines() if l.strip()]
    got = "\n".join(b.text for s in doc.sections for b in s.blocks)
    assert all(l in got for l in src_nonblank)                           # every line kept
    assert all(len(b.text.splitlines()) <= 14 for s in doc.sections for b in s.blocks)
    assert any("Compose" in s.notes for s in doc.sections)


def _make_docx(path: Path, png: bytes):
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' \
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    p = lambda text, style="": (f'<w:p>{f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>" if style else ""}'
                                f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')
    li = lambda text: f'<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'
    body = (p("Ohm's Law Basics", "Title") + p("Introduction", "Heading1") +
            p("Ohm's law relates voltage, current and resistance in a conductor.") +
            li("V is voltage in volts") + li("I is current in amperes") + li("R is resistance in ohms") +
            p("Formula", "Heading1") + p("V = I * R", "Code") + p("I = V / R", "Code") +
            '<w:tbl><w:tr><w:tc>' + p("Quantity") + '</w:tc><w:tc>' + p("Unit") + '</w:tc></w:tr>'
            '<w:tr><w:tc>' + p("Voltage") + '</w:tc><w:tc>' + p("volt (V)") + '</w:tc></w:tr></w:tbl>' +
            '<w:p><w:r><w:drawing><a:blip r:embed="rId9"/></w:drawing></w:r></w:p>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>')
        z.writestr("word/_rels/document.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId9" Type="image" Target="media/circuit.png"/></Relationships>')
        z.writestr("word/media/circuit.png", png)


def _png() -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (400, 200), (40, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def test_docx_import(tmp_path):
    f = tmp_path / "ohm.docx"
    _make_docx(f, _png())
    doc = import_document(f, tmp_path / "assets")
    assert doc.title == "Ohm's Law Basics"
    assert [s.title for s in doc.sections] == ["Introduction", "Formula"]
    blocks = [b for s in doc.sections for b in s.blocks]
    assert any(b.kind == BULLETS and len(b.items) == 3 for b in blocks)
    assert any(b.kind == CODE and "V = I * R" in b.text for b in blocks)
    assert any(b.kind == TABLE and b.rows[1] == ["Voltage", "volt (V)"] for b in blocks)
    img = [b for b in blocks if b.kind == IMAGE]
    assert img and img[0].image_path.is_file()


def _make_pptx(path: Path):
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Photosynthesis"
    tf = s.placeholders[1].text_frame
    tf.text = "Plants convert light energy into chemical energy"
    tf.add_paragraph().text = "Inputs: carbon dioxide and water"
    s.notes_slide.notes_text_frame.text = "Photosynthesis happens mainly in the leaves, inside chloroplasts."
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Equation"
    img = path.parent / "leaf.png"
    img.write_bytes(_png())
    s2.shapes.add_picture(str(img), Inches(1), Inches(2))
    prs.save(str(path))


def test_pptx_import_keeps_notes(tmp_path):
    f = tmp_path / "bio.pptx"
    _make_pptx(f)
    doc = import_document(f, tmp_path / "assets")
    assert [s.title for s in doc.sections] == ["Photosynthesis", "Equation"]
    assert "chloroplasts" in doc.sections[0].notes
    assert any(b.kind == IMAGE for b in doc.sections[1].blocks)


# ------------------------------------------------------------------ slide building
def test_slide_limits_and_no_text_loss(tmp_path):
    from src.backend.content.model import Block, ContentDocument, Section
    long_para = " ".join(f"Sentence number {i} explains a detail." for i in range(40))
    doc = ContentDocument("Physics", [Section("Forces", [
        Block(PARAGRAPH, long_para),
        Block(BULLETS, items=[f"point {i}" for i in range(15)]),
        Block(CODE, "\n".join(f"x{i} = {i}" for i in range(40)), language="python")])], "markdown")
    slides = build_slides(doc)
    for s in slides:
        assert sum(len(e.items) for e in s.elements if e.kind == BULLETS) <= MAX_BULLETS
        assert all(len(e.text.splitlines()) <= MAX_CODE_LINES for e in s.elements if e.kind == CODE)
    shown = " ".join(e.plain_text() for s in slides for e in s.elements)
    for i in range(40):
        assert f"Sentence number {i} explains" in shown
        assert f"x{i} = {i}" in shown
    for i in range(15):
        assert f"point {i}" in shown
    assert all(s.narration for s in slides)


# ------------------------------------------------------------------ conversion + rendering
@pytest.mark.parametrize("name", ["Linux_File_Permissions.md", "CounterViewModel.kt", "Python_Virtual_Environments.txt"])
def test_convert_samples_to_16x9_pdf(qapp, tmp_path, name):
    r = convert_source(SAMPLES / name, tmp_path)
    assert r.pdf.is_file() and r.manifest.is_file()
    assert _pdf_pages(r.pdf) == len(r.slides)
    w, h = _page_size(r.pdf)
    assert abs(w / h - 16 / 9) < 0.01 and w > h
    assert not r.warnings


def test_convert_docx_and_pptx(qapp, tmp_path):
    d = tmp_path / "ohm.docx"; _make_docx(d, _png())
    p = tmp_path / "bio.pptx"; _make_pptx(p)
    rd = convert_source(d, tmp_path / "d")
    rp = convert_source(p, tmp_path / "p")
    assert _pdf_pages(rd.pdf) >= 4 and _pdf_pages(rp.pdf) >= 2
    if rp.method == "rebuilt":
        assert any("chloroplasts" in s.narration for s in rp.slides)


# ------------------------------------------------------------------ profiles
def test_profiles_detect_topics_and_default_generic(tmp_path):
    profs = load_profiles()
    assert {"generic", "sap", "android", "linux", "ai_ml", "web_programming"} <= set(profs)
    assert profs[GENERIC].pronunciations == {}
    assert detect_profile((SAMPLES / "Linux_File_Permissions.md").read_text(), profs) == "linux"
    assert detect_profile((SAMPLES / "CounterViewModel.kt").read_text(), profs) == "android"
    assert detect_profile("The cat sat on the mat. Poems about the sea.", profs) == GENERIC
    sap_text = "SAP BTP subaccount with CAP and HANA Cloud, deployed to Cloud Foundry with XSUAA."
    assert detect_profile(sap_text, profs) == "sap"


def test_user_profile_overrides(tmp_path):
    (tmp_path / "chem.json").write_text('{"id": "chemistry", "name": "Chemistry", "keywords": ["molecule", "reaction", "acid"],'
                                        ' "pronunciations": {"NaCl": "sodium chloride"}}')
    profs = load_profiles([tmp_path])
    assert profs["chemistry"].pronunciations["NaCl"] == "sodium chloride"
    assert detect_profile("An acid reaction forms a molecule. The acid and the molecule react.", profs) == "chemistry"


# ------------------------------------------------------------------ end-to-end import
@pytest.mark.parametrize("name,profile", [("Linux_File_Permissions.md", "linux"), ("CounterViewModel.kt", "android")])
def test_import_worker_any_topic(qapp, tmp_path, name, profile):
    from src.backend.workers.import_worker import ImportWorker
    out, err = [], []
    w = ImportWorker(SAMPLES / name, Path(name).stem, workspace_dir=tmp_path)
    w.finished.connect(out.append); w.error.connect(err.append)
    w.run()
    assert not err, err
    proj = out[0]
    root = Path(proj.project_dir)
    assert proj.source_type in ("markdown", "code") and proj.source_file == "source/deck.pdf"
    assert (root / proj.original_source).is_file()
    assert proj.slide_count == len(proj.narrations) > 3
    assert all((root / s.image_path).is_file() for s in proj.slides)
    assert proj.content_profile == profile
    assert proj.slides[1].title and not proj.slides[1].title.startswith("Slide ")
    assert all(n.script.strip() for n in proj.narrations)


def test_generic_profile_choice_adds_no_topic_rules(qapp, tmp_path):
    from src.backend.workers.import_worker import ImportWorker
    out = []
    w = ImportWorker(SAMPLES / "Python_Virtual_Environments.txt", "Py", workspace_dir=tmp_path, profile_id="generic")
    w.finished.connect(out.append); w.run()
    assert out[0].content_profile == "generic" and out[0].settings.pronunciations == {}


# ------------------------------------------------------------------ no SAP coupling in the core
def test_core_has_no_sap_specific_code():
    pattern = re.compile(r"\b(SAP|BTP|HANA|XSUAA|OData|S/4)\b")
    offenders = []
    for f in Path("src").rglob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{f}:{i}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
