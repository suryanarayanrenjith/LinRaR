"""Headless UI checks: dialog behaviors that were reported broken."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from linrar.ui.dialogs.archive import ArchiveDialog
from linrar.ui.dialogs.extract import ExtractDialog
from linrar.core.models import ArchiveFormat
from linrar.core.settings import SETTINGS

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

work = tempfile.mkdtemp(prefix="linrar-ui-")
open(f"{work}/f.txt", "w").write("x")

d = ArchiveDialog(None, files=[f"{work}/f.txt"], base_folder=work,
                  default_name=f"{work}/test.rar")

# realtime extension sync
d._format_buttons[ArchiveFormat.ZIP].setChecked(True)
check("rar->zip ext", d.name_edit.text().endswith("test.zip"), d.name_edit.text())
d._format_buttons[ArchiveFormat.SEVENZIP].setChecked(True)
check("zip->7z ext", d.name_edit.text().endswith("test.7z"), d.name_edit.text())
d._format_buttons[ArchiveFormat.RAR5].setChecked(True)
check("7z->rar ext", d.name_edit.text().endswith("test.rar"), d.name_edit.text())

# The SFX checkbox drives the extension, and so does the kind beside it.
# Set explicitly rather than trusting the remembered default: this file runs
# against the real settings.
from linrar.core.sfx import APPIMAGE, RAR_STUB

d.sfx_combo.setCurrentIndex(d.sfx_combo.findData(APPIMAGE))
d.sfx_check.setChecked(True)
check("sfx kind reported", d.sfx_kind == APPIMAGE, d.sfx_kind)
check("sfx ext on (AppImage)", d.name_edit.text().endswith("test.AppImage"),
      d.name_edit.text())
check("an AppImage cannot be split", not d.volume_combo.isEnabled())
d.sfx_combo.setCurrentIndex(d.sfx_combo.findData(RAR_STUB))
check("sfx kind follows the combo", d.sfx_kind == RAR_STUB, d.sfx_kind)
check("sfx ext for the rar stub", d.name_edit.text().endswith("test.sfx"),
      d.name_edit.text())
check("the stub can still be split", d.volume_combo.isEnabled())
check("only the stub is rar's own -sfx",
      d.options().create_sfx and d.options().sfx_format == RAR_STUB)
d.sfx_combo.setCurrentIndex(d.sfx_combo.findData(APPIMAGE))
check("an AppImage asks rar for a plain archive",
      not d.options().create_sfx and d.options().sfx_format == APPIMAGE)
d.sfx_check.setChecked(False)
check("sfx ext off", d.name_edit.text().endswith("test.rar"), d.name_edit.text())
check("no sfx kind when off", d.sfx_kind == "", d.sfx_kind)
check("volumes available again", d.volume_combo.isEnabled())

# switching to ZIP disables (and unchecks) SFX, and retargets
d.sfx_check.setChecked(True)
d._format_buttons[ArchiveFormat.ZIP].setChecked(True)
check("zip disables sfx", not d.sfx_check.isChecked() and not d.sfx_check.isEnabled())
check("zip ext after sfx", d.name_edit.text().endswith("test.zip"), d.name_edit.text())
d._format_buttons[ArchiveFormat.RAR5].setChecked(True)

# odd names: extension appended, dotted stems preserved
d.name_edit.setText("backup.2024")
d._format_buttons[ArchiveFormat.ZIP].setChecked(True)
check("dotted stem preserved", d.name_edit.text() == "backup.2024.zip", d.name_edit.text())
d._format_buttons[ArchiveFormat.RAR5].setChecked(True)
check("dotted stem swap", d.name_edit.text() == "backup.2024.rar", d.name_edit.text())

# options() guarantees an extension
d.name_edit.setText("bare")
opts = d.options()
check("options appends ext", opts.archive_path.endswith("bare.rar"), opts.archive_path)

# volume preset parsing
d.volume_combo.setCurrentText("1457664 B")
check("floppy preset bytes", d._volume_bytes() == 1457664, d._volume_bytes())
d.volume_combo.setCurrentText("700 MB")
check("700 MB", d._volume_bytes() == 700 * 1024**2, d._volume_bytes())
d.volume_combo.setCurrentText("10")
d.unit_combo.setCurrentText("MB")
check("bare 10 + MB combo", d._volume_bytes() == 10 * 1024**2, d._volume_bytes())
d.volume_combo.setCurrentText("abc")
check("invalid volume detected", d._volume_bytes() is None)
d.volume_combo.setCurrentText("")
check("empty volume = 0", d._volume_bytes() == 0)

# extract dialog: saved defaults are actually loaded now
SETTINGS.set("extract/overwrite", "skip")
SETTINGS.set("extract/update", "update")
e = ExtractDialog(None, archive_name="x.rar", destination=work)
check("saved overwrite loaded", e.overwrite_skip.isChecked())
check("saved update loaded", e.update_update.isChecked())
SETTINGS.set("extract/overwrite", "ask")
SETTINGS.set("extract/update", "replace")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
