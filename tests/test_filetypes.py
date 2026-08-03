"""What a file is, what the viewer does with it, and what it refuses to hijack.

Two things are being pinned here.  The first is identification: the extension,
the leading bytes, and which of the two wins when they disagree.  The second is
the distinction that caused the trouble -- a ``.docx`` is a ZIP archive and a
Word document at the same time, and LinRAR has to be able to hold both ideas
at once: open it as an archive when asked, hand it to the word processor when
double-clicked, and show its *text* in the viewer rather than a hex dump.

The document files are built here rather than shipped: a few hundred bytes of
the real XML each, in the real ZIP layout, which is what the readers actually
have to cope with.
"""
import io, os, sys, tempfile, zipfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRATCH = tempfile.mkdtemp(prefix="linrar-types-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(SCRATCH, "config")
os.environ["LINRAR_SYSTEM_CONFIG"] = ""

from linrar.core import filetypes as ft
from linrar.core.filetypes import Kind

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")


def zipped(members: dict) -> bytes:
    """A ZIP container holding *members*, as the office formats really are."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


DOCX = zipped({
    "[Content_Types].xml": "<Types/>",
    "word/document.xml":
        '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
        "<w:p><w:r><w:t>The quick brown fox</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>jumps over</w:t></w:r><w:tab/>"
        "<w:r><w:t>the lazy dog &amp; friends</w:t></w:r></w:p>"
        "</w:body></w:document>",
})
PPTX = zipped({
    "ppt/slides/slide1.xml": "<p:sld><a:p><a:t>First slide</a:t></a:p></p:sld>",
    "ppt/slides/slide2.xml": "<p:sld><a:p><a:t>Second slide</a:t></a:p></p:sld>",
    "ppt/slides/slide10.xml": "<p:sld><a:p><a:t>Tenth slide</a:t></a:p></p:sld>",
})
XLSX = zipped({
    "xl/workbook.xml": "<workbook/>",
    "xl/sharedStrings.xml": "<sst><si><t>Widget</t></si><si><t>Gadget</t></si></sst>",
    "xl/worksheets/sheet1.xml":
        "<worksheet><sheetData>"
        '<row><c t="s"><v>0</v></c><c><v>12</v></c></row>'
        '<row><c t="s"><v>1</v></c><c><v>4</v></c></row>'
        "</sheetData></worksheet>",
})
ODT = zipped({
    "mimetype": "application/vnd.oasis.opendocument.text",
    "content.xml": "<office:document-content><text:h>A heading</text:h>"
                   "<text:p>A paragraph.</text:p></office:document-content>",
})
EPUB = zipped({
    "mimetype": "application/epub+zip",
    "OEBPS/chapter1.xhtml": "<html><body><p>Chapter one.</p></body></html>",
})
PLAIN_ZIP = zipped({"readme.txt": "just an archive"})

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
ELF = b"\x7fELF\x02\x01\x01" + b"\x00" * 32

print("== identifying by name")
for name, kind, label in (
    ("notes.txt", Kind.TEXT, "Text"),
    ("main.py", Kind.TEXT, "Python"),
    ("photo.JPEG", Kind.IMAGE, "JPEG image"),
    ("report.docx", Kind.DOCUMENT, "Word document"),
    ("deck.pptx", Kind.DOCUMENT, "PowerPoint presentation"),
    ("book.epub", Kind.DOCUMENT, "EPUB book"),
    ("paper.pdf", Kind.PDF, "PDF document"),
    ("song.flac", Kind.AUDIO, "FLAC audio"),
    ("clip.mkv", Kind.VIDEO, "Matroska video"),
    ("font.woff2", Kind.FONT, "Web font"),
    ("thing.so", Kind.EXECUTABLE, "Shared library"),
    ("backup.rar", Kind.ARCHIVE, "RAR archive"),
    ("Makefile", Kind.TEXT, "Makefile"),
    ("Dockerfile", Kind.TEXT, "Dockerfile"),
):
    found = ft.by_name(name)
    check(f"{name} is {label}", found.kind is kind and found.label == label,
          f"{found.kind} / {found.label}")
check("something unheard of is still described",
      ft.by_name("thing.qqq").label == "QQQ file")
check("and a file with no extension does not crash",
      ft.by_name("noextension").kind is Kind.UNKNOWN)
check("a path is reduced to its name", ft.by_name("/a/b/c.png").kind is Kind.IMAGE)

print("\n== identifying by content")
check("a PNG is a PNG whatever it is called",
      ft.identify(name="lies.txt", data=PNG).kind is Kind.IMAGE)
check("an ELF is a program", ft.identify(name="x", data=ELF).kind is Kind.EXECUTABLE)
check("text is text", ft.identify(name="x", data=b"hello\nworld\n").kind is Kind.TEXT)
check("and the bytes beat the extension",
      ft.identify(name="notes.txt", data=PNG).source == "content")
check("an empty file falls back to its name",
      ft.identify(name="notes.txt", data=b"").kind is Kind.TEXT)

print("\n== a ZIP that is a document, and one that is not")
check("a plain ZIP is an archive",
      ft.identify(name="stuff.zip", data=PLAIN_ZIP).kind is Kind.ARCHIVE)
check("a .docx is a document, though the bytes are a ZIP",
      ft.identify(name="report.docx", data=DOCX).kind is Kind.DOCUMENT)
check("and it is named as one",
      ft.identify(name="report.docx", data=DOCX).label == "Word document")
check("is_document_container agrees", ft.is_document_container("report.docx"))
check("for every office format",
      all(ft.is_document_container(f"x.{e}")
          for e in ("docx", "xlsx", "pptx", "odt", "ods", "odp", "epub")))
check("but not for a real archive", not ft.is_document_container("x.zip"))
check("nor for a .rar", not ft.is_document_container("x.rar"))
check("nor for a jar, which is a program's archive",
      not ft.is_document_container("x.jar"))

print("\n== reading the documents")
text = ft.document_text(data=DOCX)
check("a Word document gives up its text", "quick brown fox" in (text or ""), text)
check("paragraphs become lines", "\n" in (text or ""))
check("tabs survive", "\t" in (text or ""), repr(text))
check("XML entities are decoded", "& friends" in (text or ""), text)
check("and no angle brackets are left", "<w:" not in (text or ""))

slides = ft.document_text(data=PPTX)
check("a presentation gives up its slides", "First slide" in (slides or ""))
check("each slide is labelled", "--- Slide 1 ---" in (slides or ""))
check("slide 10 comes after slide 2, not after slide 1",
      (slides or "").index("Second slide") < (slides or "").index("Tenth slide"),
      slides)

sheet = ft.document_text(data=XLSX)
check("a workbook gives up its cells", "Widget" in (sheet or ""), sheet)
check("shared strings are resolved, not printed as indexes",
      "Gadget" in (sheet or "") and "\t4" in (sheet or ""), sheet)
check("rows are tab separated", "Widget\t12" in (sheet or ""), sheet)

odt = ft.document_text(data=ODT)
check("an OpenDocument gives up its text", "A paragraph." in (odt or ""), odt)
check("headings come with it", "A heading" in (odt or ""))

epub = ft.document_text(data=EPUB)
check("an EPUB gives up its chapters", "Chapter one." in (epub or ""), epub)

check("a plain ZIP is not a document", ft.document_text(data=PLAIN_ZIP) is None)
check("nor is a PNG", ft.document_text(data=PNG) is None)
check("nor is nonsense", ft.document_text(data=b"not a zip at all") is None)
check("and a truncated ZIP is refused rather than raising",
      ft.document_text(data=DOCX[:40]) is None)

print("\n== decoding and dumping")
check("UTF-8 comes back", ft.decode("héllo".encode()) == "héllo")
check("a BOM is honoured",
      ft.decode(b"\xef\xbb\xbfhello") == "hello")
check("UTF-16 is understood", ft.decode("hi".encode("utf-16")) == "hi")
check("and arbitrary bytes never raise", isinstance(ft.decode(bytes(range(256))), str))
dump = ft.hex_dump(b"LinRAR\x00\x01")
check("the dump has an offset", dump.startswith("00000000"))
check("it has the bytes", "4c 69 6e" in dump, dump)
check("and the printable column", "|LinRAR..|" in dump, dump)
check("a big file is cut off", "more bytes" in ft.hex_dump(b"x" * 100000))

print("\n== what counts as text")
check("plain text does", ft._looks_textual(b"hello world\n"))
check("a NUL byte does not", not ft._looks_textual(b"hello\x00world"))
check("mostly-binary does not", not ft._looks_textual(bytes(range(0, 32)) * 10))
check("UTF-8 punctuation does", ft._looks_textual("— é ü".encode()))
check("and an empty file does", ft._looks_textual(b""))

print("\n== the viewer")
from PyQt6.QtWidgets import QApplication      # noqa: E402

app = QApplication.instance() or QApplication([])
from linrar.ui.dialogs.misc import ViewerDialog     # noqa: E402
from linrar.ui.filelist import ListingItem          # noqa: E402

viewer = ViewerDialog(None, "report.docx", DOCX, "/tmp/report.docx")
check("a Word document opens as its text",
      "quick brown fox" in viewer.text_view.toPlainText(),
      viewer.text_view.toPlainText()[:80])
check("the window says what it is holding",
      viewer.file_type.label == "Word document")
check("it explains that this is only the text",
      "Formatting" in viewer.note.text(), viewer.note.text())
check("and offers to hand it to the real application",
      viewer.btn_open.isEnabled())
viewer._show_hex()
check("the bytes are still one click away",
      viewer.text_view.toPlainText().startswith("00000000"))
viewer.close()

viewer = ViewerDialog(None, "thing", ELF)
check("a binary is identified rather than just dumped",
      viewer.file_type.kind is Kind.EXECUTABLE)
check("its bytes are shown", viewer.text_view.toPlainText().startswith("00000000"))
check("with a sentence saying why", "nothing readable" in viewer.note.text(),
      viewer.note.text())
check("and Open with is disabled when there is no file on disk",
      not viewer.btn_open.isEnabled())
viewer.close()

viewer = ViewerDialog(None, "notes.txt", b"line one\nline two\n")
check("text is shown as text",
      viewer.text_view.toPlainText().startswith("line one"))
check("with no explanation needed", not viewer.note.isVisible())
viewer.close()

viewer = ViewerDialog(None, "stuff.zip", PLAIN_ZIP, "/tmp/stuff.zip")
# isHidden(), not isVisible(): a widget inside a dialog nobody has shown is
# never "visible", but it does remember whether it was hidden on purpose.
check("an archive offers to open in LinRAR", not viewer.btn_archive.isHidden())
viewer._open_in_linrar()
check("and says so to the caller", viewer.open_as_archive)
viewer.close()

viewer = ViewerDialog(None, "empty.bin", b"")
check("an empty file does not break the viewer", viewer is not None)
viewer.close()

print("\n== the Type column")
for name, expected in (
    ("holiday.jpg", "JPEG image"),
    ("report.docx", "Word document"),
    ("notes.md", "Markdown"),
    ("backup.rar", "LinRAR archive"),
    ("photos.zip", "LinRAR ZIP archive"),
    ("comic.cbz", "LinRAR comic book archive"),
    ("thing.qqq", "QQQ file"),
):
    item = ListingItem(name=name, path="/tmp/" + name)
    check(f"{name} reads as {expected}", item.type_name == expected,
          item.type_name)
check("a folder is a folder",
      ListingItem(name="d", path="/d", is_dir=True).type_name == "File folder")
check("the parent link has no type",
      ListingItem(name="..", path="/", is_parent=True).type_name == "")

print("\n== identifying a file with no extension to go on")
nameless = os.path.join(SCRATCH, "programme")
with open(nameless, "wb") as handle:
    handle.write(ELF)
check("a binary with no extension is still identified",
      ft.identify_file(nameless).kind is Kind.EXECUTABLE,
      ft.identify_file(nameless))
readme = os.path.join(SCRATCH, "somefile")
with open(readme, "w") as handle:
    handle.write("plain words, no extension\n")
check("and so is text", ft.identify_file(readme).kind is Kind.TEXT)
check("an empty one is left alone",
      ft.identify_file(os.path.join(SCRATCH, "nothing")).kind is Kind.UNKNOWN)
check("a name with an extension never reaches the disk",
      ft.identify_file("/does/not/exist/photo.png").kind is Kind.IMAGE)
check("the answer is remembered rather than re-read",
      ft.identify_file(nameless) == ft.identify_file(nameless))

print("\n== icons")
for name, icon in (
    ("report.docx", "file-word"), ("letter.doc", "file-word"),
    ("budget.xlsx", "file-excel"), ("data.csv", "file-excel"),
    ("deck.pptx", "file-powerpoint"), ("talk.odp", "file-powerpoint"),
    ("paper.pdf", "file-pdf"),
    ("book.epub", "file-document"), ("notes.odt", "file-document"),
    ("readme.txt", "file-text"), ("notes.md", "file-text"),
    ("main.py", "file-code"), ("index.html", "file-code"),
    ("app.js", "file-code"), ("Makefile", "file-code"),
    ("photo.jpg", "file-image"), ("logo.svg", "file-image"),
    ("song.flac", "file-audio"), ("clip.mkv", "file-video"),
    ("face.ttf", "file-font"), ("libc.so", "file-exec"),
    ("store.sqlite", "file-data"), ("ubuntu.iso", "file-disc"),
    ("id_rsa.pem", "file-key"),
    ("backup.rar", "archive-small"), ("src.tar.gz", "archive-small"),
):
    check(f"{name} is drawn as {icon}", ft.icon_for(name) == icon,
          ft.icon_for(name))
check("something unheard of gets the plain page",
      ft.icon_for("thing.qqq") == "file")

from linrar.ui import icons as icon_set               # noqa: E402

drawn = set(icon_set.names())
check("every icon the tables name is one that exists",
      set(ft._ICON_BY_EXTENSION.values()) <= drawn,
      sorted(set(ft._ICON_BY_EXTENSION.values()) - drawn))
check("and so is every fallback",
      set(ft._ICON_BY_KIND.values()) <= drawn,
      sorted(set(ft._ICON_BY_KIND.values()) - drawn))
check("there is a drawing for every kind of file",
      set(ft._ICON_BY_KIND) == set(Kind),
      sorted(k.value for k in set(Kind) - set(ft._ICON_BY_KIND)))
check("and they are not all the same one",
      len(set(ft._ICON_BY_KIND.values())) >= 9)
for name in sorted(n for n in drawn if n.startswith("file-")):
    pixmap = icon_set.pixmap(name, 16)
    check(f"{name} renders at 16px", not pixmap.isNull() and pixmap.width() > 0)

print("\n== what the list shows")
for name, icon, label in (
    ("report.docx", "file-word", "Word document"),
    ("book.epub", "file-document", "EPUB book"),
    ("ubuntu.iso", "file-disc", "Disc image"),
    ("backup.rar", "archive-small", "LinRAR archive"),
):
    item = ListingItem(name=name, path="")
    check(f"{name} is drawn as {icon}", item.icon_name == icon, item.icon_name)
    check(f"{name} reads as {label}", item.type_name == label, item.type_name)
check("an archive member is never read from disk",
      ListingItem(name="x", path="in/archive",
                  entry=object()).type_name == "File")

print("\n== the self-extracting dialogs")
from linrar.core.sfx import APPIMAGE, RAR_STUB          # noqa: E402
from linrar.ui.dialogs.sfx import SfxDialog, SfxKindDialog   # noqa: E402

options = SfxDialog(None, archive_path="/tmp/demo.rar")
check("the options window is the AppImage's",
      "AppImage" in options.windowTitle(), options.windowTitle())
check("and says so it is only that", options.sfx_format == APPIMAGE)
check("there is no format to choose in it",
      not hasattr(options, "stub_radio") and not hasattr(options, "appimage_radio"))
check("nor a button group for one", not hasattr(options, "format_group"))
check("the readiness line stays, because it decides whether this can work",
      hasattr(options, "state_label") and "Architecture" in options.state_label.text())
check("every page is enabled: nothing here is greyed out any more",
      options.tabs.isEnabled())
check("and it still produces options", options.options() is not None)
options.close()

chooser = SfxKindDialog(None, archive_path="/tmp/demo.rar")
check("the chooser starts undecided", chooser.chosen == "")
chooser._choose(RAR_STUB)
check("choosing the stub is reported", chooser.chosen == RAR_STUB)
chooser2 = SfxKindDialog(None, archive_path="/tmp/demo.rar")
chooser2._choose(APPIMAGE)
check("and so is choosing the AppImage", chooser2.chosen == APPIMAGE)
from PyQt6.QtWidgets import QLabel                      # noqa: E402

check("it names the archive it is working on",
      any("demo.rar" in label.text() for label in chooser2.findChildren(QLabel)))
check("and explains what each choice means",
      any("takes no options" in label.text()
          for label in chooser2.findChildren(QLabel)))
chooser.close(); chooser2.close()

source = open(os.path.join(ROOT, "linrar/ui/main_window.py")).read()
check("Convert to SFX asks which kind before opening the options",
      source.index("SfxKindDialog(self") < source.index("SfxDialog(self"),
      "the chooser must come first")
check("and the stub never reaches the options window",
      "chooser.chosen == sfx.RAR_STUB" in source)
archive_source = open(os.path.join(ROOT, "linrar/ui/dialogs/archive.py")).read()
check("the Add dialog keeps its own kind selector",
      "self.sfx_combo" in archive_source)
check("and its Options button explains that the stub has none",
      "takes no options" in archive_source)

print("\n== the tables themselves")
check("every extension maps to a real kind",
      all(isinstance(k, Kind) for k, _l in ft.EXTENSIONS.values()))
check("and to a non-empty label",
      all(label.strip() for _k, label in ft.EXTENSIONS.values()))
check("there are several hundred of them", len(ft.EXTENSIONS) > 250,
      len(ft.EXTENSIONS))
check("every document container has a label",
      all(v.strip() for v in ft.DOCUMENT_CONTAINERS.values()))
check("no container is also claimed as a plain archive",
      not ({"docx", "xlsx", "pptx", "odt", "epub"} & {"zip", "rar", "7z"}))
check("svg is treated as text, which LinRAR can actually show",
      ft.by_name("drawing.svg").kind is Kind.TEXT)

import shutil                                        # noqa: E402
shutil.rmtree(SCRATCH, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
