"""The archive dialog's name/extension and volume-size handling.

Started life as a reproduction script for the extension bug; kept as checks so
the behaviour it pinned down cannot drift back.
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from linrar.ui.dialogs.archive import ArchiveDialog
from linrar.core.models import ArchiveFormat
from linrar.core.profiles import PROFILES

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

work = tempfile.mkdtemp(prefix="linrar-dialog-")
open(f"{work}/a.txt", "w").write("x")

dialog = ArchiveDialog(None, files=[f"{work}/a.txt"], base_folder=work,
                       default_name=f"{work}/test.rar")
check("starts with the name it was given",
      dialog.name_edit.text().endswith("test.rar"), dialog.name_edit.text())

# cmd_add applies the default profile straight after building the dialog.
dialog.apply_profile(PROFILES.default())
check("the default profile leaves the name alone",
      dialog.name_edit.text().endswith("test.rar"), dialog.name_edit.text())

for fmt, suffix in (
    (ArchiveFormat.ZIP, "test.zip"),
    (ArchiveFormat.SEVENZIP, "test.7z"),
    (ArchiveFormat.RAR5, "test.rar"),
):
    dialog._format_buttons[fmt].setChecked(True)
    check(f"picking {fmt.label} retargets the extension",
          dialog.name_edit.text().endswith(suffix), dialog.name_edit.text())

dialog.name_edit.setText("myarchive")
dialog._format_buttons[ArchiveFormat.ZIP].setChecked(True)
check("a name with no extension gets one",
      dialog.name_edit.text() == "myarchive.zip", dialog.name_edit.text())

dialog.name_edit.setText("myarchive")
check("options() fills the extension in too",
      dialog.options().archive_path.endswith("myarchive.zip"),
      dialog.options().archive_path)

for text, expected in (
    ("10", 10 * 1024**2),            # bare number, unit from the combo (MB)
    ("700M", 700 * 1024**2),         # unit written in the text wins
    ("1457664 B", 1457664),          # the floppy preset carries its own unit
    ("", 0),                         # empty means "do not split"
):
    dialog.volume_combo.setCurrentText(text)
    check(f"volume size {text!r}", dialog._volume_bytes() == expected,
          dialog._volume_bytes())

dialog.volume_combo.setCurrentText("not a size")
check("nonsense volume size is rejected", dialog._volume_bytes() is None)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
