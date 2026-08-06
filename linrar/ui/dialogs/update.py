"""The update window: checking, downloading, installing, and saying so.

An updater that replaces the program somebody is using has to be legible while
it does it.  This one shows the stages it will go through before it starts,
ticks them off as they pass, gives the download a byte count, a speed and a
time remaining, and keeps every line the worker logged in a details pane that
can be copied into a bug report.  Nothing happens behind the user's back:
there is one window, it is in front, and it says what it is doing.

The work itself is in :mod:`linrar.core.updater`, which knows nothing about
widgets; this module is the part that watches.
"""

from __future__ import annotations

import html
import os
import time
from typing import Optional

from PyQt6.QtCore import Qt, QProcess, QTimer, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...core import updater
from ...core.models import format_size_short
from ...core.settings import SETTINGS
from ...core.tasks import UpdateTask
from ...core.updater import Update
from ... import version as versions
from .. import icons, policy, theme

#: How often a start-up check will actually go to the network.  LinRAR is
#: opened from a file manager's right-click menu, which can mean a dozen
#: launches in a minute; asking the server every time would be rude without
#: telling the user anything it did not tell them ten seconds ago.
START_CHECK_INTERVAL = 3600

#: How long after the window appears the start-up check runs.  Long enough for
#: the interface to have finished drawing, short enough to feel prompt.
START_CHECK_DELAY_MS = 2500

_PENDING, _CURRENT, _DONE, _FAILED = "pending", "current", "done", "failed"
_GLYPHS = {_PENDING: "·", _CURRENT: "▶", _DONE: "✓", _FAILED: "✕"}

#: Workers that are still running, kept alive here rather than by whatever
#: window started them.  A QThread destroyed while it is running takes the
#: process down with it, and a window the user closed must not be able to do
#: that: it disconnects its worker and walks away, and the worker finishes
#: into nothing.
_RUNNING: set = set()


def _keep(task) -> None:
    _RUNNING.add(task)
    task.finished.connect(lambda: _RUNNING.discard(task))


def _bold(widget: QLabel) -> QLabel:
    font = widget.font()
    font.setBold(True)
    widget.setFont(font)
    return widget


class StageList(QWidget):
    """The steps an update goes through, ticked off as they pass."""

    def __init__(self, stages, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key, title, _weight in stages:
            row = QHBoxLayout()
            row.setSpacing(8)
            glyph = QLabel(_GLYPHS[_PENDING])
            glyph.setFixedWidth(14)
            glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption = QLabel(title)
            caption.setObjectName("Hint")
            row.addWidget(glyph)
            row.addWidget(caption, 1)
            layout.addLayout(row)
            self.rows[key] = (glyph, caption)

    def set_state(self, key: str, state: str) -> None:
        pair = self.rows.get(key)
        if pair is None:
            return
        glyph, caption = pair
        glyph.setText(_GLYPHS[state])
        glyph.setObjectName(
            {"done": "Success", "current": "", "failed": "Failure",
             "pending": "Hint"}[state]
        )
        caption.setObjectName("" if state == _CURRENT else "Hint")
        font = caption.font()
        font.setBold(state == _CURRENT)
        caption.setFont(font)
        for widget in (glyph, caption):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def advance_to(self, key: str) -> None:
        """Mark everything before *key* done, *key* current, the rest pending."""
        seen = False
        for name in self.rows:
            if name == key:
                seen = True
                self.set_state(name, _CURRENT)
            elif seen:
                self.set_state(name, _PENDING)
            else:
                self.set_state(name, _DONE)

    def finish(self) -> None:
        for name in self.rows:
            self.set_state(name, _DONE)

    def fail_current(self) -> None:
        for name, (glyph, _caption) in self.rows.items():
            if glyph.text() == _GLYPHS[_CURRENT]:
                self.set_state(name, _FAILED)


class UpdateDialog(QDialog):
    """Help > Check for updates, and everything that follows from it.

    One window for the whole business: it checks, reports, offers, downloads,
    installs and then asks to restart, rather than handing the user from dialog
    to dialog.  *auto_install* is what the start-up check passes when the user
    has asked for updates to be installed on their own; the window still
    appears and still shows every stage, because "automatic" means "without
    being asked", not "without being told".
    """

    #: Emitted once an update is in place, so the main window can react.
    updated = pyqtSignal(str)

    def __init__(self, parent=None, auto_install: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("LinRAR Update")
        self.setWindowIcon(icons.icon("app"))
        self.setModal(True)
        self.setMinimumWidth(560)

        self.auto_install = auto_install
        self.update: Optional[Update] = None
        self.task: Optional[UpdateTask] = None
        self._installing = False
        self._finished = False
        self._log: list[str] = []
        self._stage = ""
        self._speed_at = 0.0
        self._speed_bytes = 0
        self._speed = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        layout.addLayout(self._header())
        layout.addWidget(self._rule())

        self.pages = QStackedWidget()
        self.page_check = self._checking_page()
        self.page_result = self._result_page()
        self.page_work = self._working_page()
        self.page_done = self._done_page()
        for page in (self.page_check, self.page_result,
                     self.page_work, self.page_done):
            self.pages.addWidget(page)
        layout.addWidget(self.pages, 1)

        self.details_button = QPushButton("Show details")
        self.details_button.setCheckable(True)
        self.details_button.setFlat(True)
        self.details_button.toggled.connect(self._toggle_details)
        # Every line the worker logged, which is exactly what a bug report
        # about a failed update needs to carry.
        self.copy_button = QPushButton("Copy log")
        self.copy_button.setFlat(True)
        self.copy_button.setVisible(False)
        self.copy_button.clicked.connect(self._copy_log)
        details_row = QHBoxLayout()
        details_row.setSpacing(4)
        details_row.addWidget(self.details_button)
        details_row.addWidget(self.copy_button)
        details_row.addStretch(1)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setVisible(False)
        self.details.setMinimumHeight(150)
        self.details.setFont(_mono())
        layout.addLayout(details_row)
        layout.addWidget(self.details)

        self.buttons = QDialogButtonBox()
        self.btn_update = self.buttons.addButton(
            "Update now", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.btn_restart = self.buttons.addButton(
            "Restart LinRAR", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.btn_skip = self.buttons.addButton(
            "Skip this version", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.btn_notes = self.buttons.addButton(
            "Release page", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.btn_close = self.buttons.addButton(
            "Close", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.btn_update.setIcon(icons.icon("download"))
        self.btn_restart.setIcon(icons.icon("refresh"))
        self.btn_update.clicked.connect(self.start_install)
        self.btn_restart.clicked.connect(self._restart)
        self.btn_skip.clicked.connect(self._skip)
        self.btn_notes.clicked.connect(self._open_release_page)
        self.btn_close.clicked.connect(self.close)
        layout.addWidget(self.buttons)

        self._show_page(self.page_check)
        self._set_buttons(close=True)

    # -- construction ------------------------------------------------------

    def _header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)
        self.header_icon = QLabel()
        self.header_icon.setPixmap(icons.pixmap("package", 40))
        self.header_icon.setFixedSize(44, 44)
        header.addWidget(self.header_icon, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(2)
        self.title_label = _bold(QLabel("Checking for updates..."))
        font = self.title_label.font()
        font.setPointSizeF(font.pointSizeF() + 1.5)
        self.title_label.setFont(font)
        self.subtitle_label = QLabel(
            f"This copy is LinRAR {versions.describe_state()}"
        )
        self.subtitle_label.setObjectName("Hint")
        self.subtitle_label.setWordWrap(True)
        text.addWidget(self.title_label)
        text.addWidget(self.subtitle_label)
        header.addLayout(text, 1)
        return header

    def _rule(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _checking_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        self.check_bar = QProgressBar()
        self.check_bar.setRange(0, 0)          # busy: length is unknowable
        self.check_bar.setTextVisible(False)
        layout.addWidget(self.check_bar)
        hint = QLabel(f"Asking {versions.MANIFEST_URL}")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _result_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        self.facts_box = QGroupBox("This release")
        facts = QFormLayout(self.facts_box)
        facts.setContentsMargins(10, 8, 10, 8)
        self.fact_version = QLabel("-")
        self.fact_date = QLabel("-")
        self.fact_size = QLabel("-")
        self.fact_channel = QLabel("-")
        facts.addRow("Version", _bold(self.fact_version))
        facts.addRow("Published", self.fact_date)
        facts.addRow("Download", self.fact_size)
        facts.addRow("Channel", self.fact_channel)
        layout.addWidget(self.facts_box)

        self.notes = QTextBrowser()
        # The notes come off the network, so links in them are not followed
        # blindly: setOpenExternalLinks would hand any scheme at all straight
        # to the desktop, and "javascript:" or "file:" in a release note is a
        # trick, not a link.  _open_link decides instead.
        self.notes.setOpenExternalLinks(False)
        self.notes.setOpenLinks(False)
        self.notes.anchorClicked.connect(self._open_link)
        self.notes.setMinimumHeight(180)
        layout.addWidget(self.notes, 1)

        self.auto_check = QCheckBox("Check for updates when LinRAR starts")
        self.auto_check.setChecked(bool(SETTINGS.get("update/check_on_start")))
        self.auto_check.toggled.connect(self._set_auto_check)
        policy.guard(self.auto_check, "update/check_on_start")
        layout.addWidget(self.auto_check)

        self.blocked_label = QLabel()
        self.blocked_label.setObjectName("Warning")
        self.blocked_label.setWordWrap(True)
        self.blocked_label.setVisible(False)
        layout.addWidget(self.blocked_label)
        return page

    def _working_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Every stage, listed before the first one starts: an updater that
        # reveals its plan one step at a time reads as though it is improvising.
        self.stages = StageList(updater.STAGES)
        layout.addWidget(self.stages)

        layout.addWidget(self._rule())

        self.stage_label = _bold(QLabel("Preparing..."))
        layout.addWidget(self.stage_label)
        self.stage_bar = QProgressBar()
        self.stage_bar.setRange(0, 100)
        layout.addWidget(self.stage_bar)
        self.stats_label = QLabel(" ")
        self.stats_label.setObjectName("Hint")
        layout.addWidget(self.stats_label)

        overall_caption = QLabel("Overall")
        overall_caption.setObjectName("Hint")
        layout.addWidget(overall_caption)
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        layout.addWidget(self.overall_bar)
        layout.addStretch(1)
        return page

    def _done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(8)
        self.done_label = QLabel()
        self.done_label.setWordWrap(True)
        layout.addWidget(self.done_label)
        self.done_hint = QLabel()
        self.done_hint.setObjectName("Hint")
        self.done_hint.setWordWrap(True)
        self.done_hint.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.done_hint)
        layout.addStretch(1)
        return page

    # -- state -------------------------------------------------------------

    def _show_page(self, page: QWidget) -> None:
        self.pages.setCurrentWidget(page)

    def _set_buttons(self, *, update=False, restart=False, skip=False,
                     notes=False, close=False, cancel=False) -> None:
        self.btn_update.setVisible(update)
        self.btn_restart.setVisible(restart)
        self.btn_skip.setVisible(skip)
        self.btn_notes.setVisible(notes)
        self.btn_close.setVisible(close or cancel)
        self.btn_close.setText("Cancel" if cancel else "Close")
        if update:
            self.btn_update.setDefault(True)
        elif restart:
            self.btn_restart.setDefault(True)

    def _headline(self, title: str, subtitle: str, icon_name: str,
                  style: str = "") -> None:
        self.title_label.setText(title)
        self.title_label.setObjectName(style)
        self.title_label.style().unpolish(self.title_label)
        self.title_label.style().polish(self.title_label)
        self.subtitle_label.setText(subtitle)
        self.header_icon.setPixmap(icons.pixmap(icon_name, 40))

    def _set_auto_check(self, on: bool) -> None:
        """Saved as it is clicked: this box is not part of the OK/Cancel pair."""
        SETTINGS.set("update/check_on_start", on)
        SETTINGS.sync()

    def _toggle_details(self, shown: bool) -> None:
        self.details.setVisible(shown)
        self.copy_button.setVisible(shown)
        self.details_button.setText("Hide details" if shown else "Show details")
        if not shown:
            self.adjustSize()

    def _copy_log(self) -> None:
        QApplication.clipboard().setText("\n".join(self._log))
        self.copy_button.setText("Copied")
        QTimer.singleShot(1500, lambda: self.copy_button.setText("Copy log"))

    def _log_line(self, line: str) -> None:
        self._log.append(line)
        self.details.appendPlainText(line)

    # -- checking ----------------------------------------------------------

    def start_check(self) -> None:
        """Ask the server what the newest release is."""
        self._show_page(self.page_check)
        self._headline("Checking for updates...",
                       f"This copy is LinRAR {versions.describe_state()}", "refresh")
        self._set_buttons(cancel=True)
        self._log_line(f"Checking for updates ({time.strftime('%H:%M:%S')})")

        allow_pre = bool(SETTINGS.get("update/prereleases"))
        self.task = UpdateTask(
            lambda ctx: updater.check(ctx, allow_prerelease=allow_pre),
            install=False,
        )
        _keep(self.task)
        self.task.messageLogged.connect(self._log_line)
        self.task.checked.connect(self._on_checked)
        self.task.failed.connect(self._on_failed)
        self.task.cancelled.connect(self.reject)
        self.task.start()
        SETTINGS.set("update/last_check", time.strftime("%Y-%m-%dT%H:%M:%S"))

    def _on_checked(self, found: Optional[Update]) -> None:
        self.task = None
        if found is None:
            self._headline(
                "LinRAR is up to date",
                f"Version {versions.installed_version()} is the newest release."
                + (" It will be running once LinRAR is restarted."
                   if versions.restart_pending() else ""),
                "package", "Success",
            )
            self._show_page(self.page_result)
            self.facts_box.setVisible(False)
            self.notes.setVisible(False)
            self.blocked_label.setVisible(False)
            self.auto_check.setVisible(True)
            self._set_buttons(close=True)
            return

        self.update = found
        self.present(found)

    def present(self, found: Update) -> None:
        """Show what is available, and whether it can be installed here."""
        self._headline(
            f"LinRAR {found.version} is available",
            f"You are running {versions.describe_state()}.",
            "package-alert",
        )
        self.fact_version.setText(found.version)
        self.fact_date.setText(found.date or "-")
        self.fact_size.setText(
            f"{format_size_short(found.size)}  ({found.artifact.name})"
            if found.artifact else "-"
        )
        self.fact_channel.setText(
            "Pre-release" if found.prerelease else "Stable"
        )
        self._render_notes(found)
        self.facts_box.setVisible(True)
        self.notes.setVisible(True)
        self._show_page(self.page_result)

        allowed = updater.eligibility()
        if not allowed:
            self.blocked_label.setText(
                f"{allowed.reason}\n{allowed.suggestion}"
            )
            self.blocked_label.setVisible(True)
            self._set_buttons(notes=True, close=True)
            self._log_line(f"Not updatable here: {allowed.reason}")
            return

        self.blocked_label.setVisible(False)
        self._set_buttons(update=True, skip=True, notes=True, close=True)
        if self.auto_install:
            self._log_line("Automatic updates are on; installing.")
            QTimer.singleShot(0, self.start_install)

    def _render_notes(self, found: Update) -> None:
        colors = theme.current()
        if found.notes.strip():
            self.notes.setMarkdown(
                f"## What changed in {found.version}\n\n{found.notes}"
            )
            return
        # Everything from the manifest is escaped: a release_url carrying a
        # quote and a tag of its own would otherwise write its own markup into
        # this pane.
        link = html.escape(found.release_url, quote=True)
        self.notes.setHtml(
            f"<p style='color:{colors.text_dim}'>This release came with no "
            f'notes. See <a href="{link}">the release page</a>.</p>'
        )

    def _open_link(self, url) -> None:
        """Open a link from the release notes, if it is one worth opening."""
        if url.scheme().lower() in ("http", "https"):
            QDesktopServices.openUrl(url)
            return
        self._log_line(f"Ignored a link the notes offered: {url.toString()}")

    # -- installing --------------------------------------------------------

    def start_install(self) -> None:
        if self.update is None or self._installing:
            return
        allowed = updater.eligibility()
        if not allowed:
            QMessageBox.warning(self, "LinRAR Update",
                                f"{allowed.reason}\n\n{allowed.suggestion}")
            return

        found = self.update
        self._installing = True
        self._speed_at = time.monotonic()
        self._speed_bytes = 0
        self._headline(f"Installing LinRAR {found.version}",
                       "Do not close LinRAR until this finishes.", "download")
        self._show_page(self.page_work)
        self._set_buttons(cancel=True)
        # The check really did happen, so it is shown as done rather than as a
        # stage that is somehow being skipped.
        self.stages.set_state("check", _DONE)
        self.stages.advance_to("download")
        self.overall_bar.setValue(updater.overall_percent("download", 0))
        self._log_line(f"Installing {found.version} from {found.artifact.url}")

        preference = str(SETTINGS.get("admin/method") or "auto")
        self.task = UpdateTask(
            lambda ctx: updater.run_update(found, ctx, elevate=preference),
            install=True,
        )
        _keep(self.task)
        self.task.stageChanged.connect(self._on_stage)
        self.task.progressChanged.connect(self._on_progress)
        self.task.messageLogged.connect(self._log_line)
        self.task.installed.connect(self._on_installed)
        self.task.failed.connect(self._on_failed)
        self.task.cancelled.connect(self._on_cancelled)
        self.task.start()

    def _on_stage(self, key: str, title: str) -> None:
        self._stage = key
        self.stages.advance_to(key)
        self.stage_label.setText(f"{title}...")
        self.stage_bar.setValue(0)
        self.stats_label.setText(" ")
        self._speed_at = time.monotonic()
        self._speed_bytes = 0

    def _on_progress(self, percent: int, done: int, total: int) -> None:
        self.stage_bar.setValue(percent)
        overall = updater.overall_percent(self._stage, percent)
        self.overall_bar.setValue(overall)
        self.setWindowTitle(f"{overall}%  -  LinRAR Update")
        self.stats_label.setText(self._stats_text(done, total))

    def _stats_text(self, done: int, total: int) -> str:
        if not total:
            return " "
        now = time.monotonic()
        elapsed = now - self._speed_at
        if elapsed >= 0.5 and done > self._speed_bytes:
            self._speed = (done - self._speed_bytes) / elapsed
            self._speed_bytes = done
            self._speed_at = now
        text = f"{format_size_short(done)} of {format_size_short(total)}"
        if self._speed > 0:
            text += f"   -   {format_size_short(self._speed)}/s"
            left = (total - done) / self._speed
            if left >= 1:
                text += f"   -   about {_duration(left)} left"
        return text

    def _on_installed(self, backup: str) -> None:
        self.task = None
        self._installing = False
        self._finished = True
        version = self.update.version if self.update else ""
        self.stages.finish()
        self.overall_bar.setValue(100)
        self.setWindowTitle("LinRAR Update")
        self._headline(f"LinRAR {version} is installed",
                       "Restart LinRAR to start using it.", "package",
                       "Success")
        self.done_label.setText(
            f"<b>LinRAR {version} has been installed.</b><br>"
            f"Everything on disk now says {versions.installed_version()}; the "
            f"copy still running is {versions.__version__}, and will be until "
            "it is restarted."
        )
        self.done_hint.setText(
            f"The previous version was kept at {backup}"
            if backup else
            "The old version's files were removed and the download cache "
            "cleared, nothing was left behind."
        )
        self._show_page(self.page_done)
        self._set_buttons(restart=True, close=True)
        SETTINGS.set("update/skipped", "")
        SETTINGS.sync()
        self.updated.emit(version)

    def _on_cancelled(self) -> None:
        self.task = None
        self._installing = False
        self.stages.fail_current()
        self._headline("Update cancelled",
                       "Nothing was changed; the previous version is in place.",
                       "package", "Warning")
        self._log_line("Cancelled by the user.")
        self._set_buttons(close=True)

    def _on_failed(self, error: Exception) -> None:
        self.task = None
        self._installing = False
        self.stages.fail_current()
        message = getattr(error, "message", str(error))
        detail = getattr(error, "detail", "")
        self._headline("The update did not go through", message, "package-alert",
                       "Failure")
        self._log_line(f"FAILED: {message}")
        if detail:
            self._log_line(detail)
        self.done_label.setText(f"<b>{message}</b>")
        self.done_hint.setText(
            (detail or "").strip()
            + ("\n\n" if detail else "")
            + "Nothing was left half-installed: the version that was working "
              "is still the one in place."
        )
        self._show_page(self.page_done)
        self._set_buttons(notes=self.update is not None, close=True)
        if not self.details_button.isChecked():
            self.details_button.setChecked(True)

    # -- the buttons -------------------------------------------------------

    def _skip(self) -> None:
        if self.update is None:
            return
        SETTINGS.set("update/skipped", self.update.version)
        SETTINGS.sync()
        self._log_line(f"{self.update.version} will not be offered again.")
        self.accept()

    def _open_release_page(self) -> None:
        """Open the release page, but only when the manifest named a web one.

        ``release_url`` arrives over the network like everything else in the
        manifest, and a button that hands whatever it says to the desktop is a
        button that will eventually be asked to run something.
        """
        from PyQt6.QtCore import QUrl

        target = self.update.release_url if self.update else versions.RELEASES_URL
        url = QUrl(target)
        if url.scheme().lower() not in ("http", "https"):
            self._log_line(f"Not opening {target}: only web pages are followed.")
            url = QUrl(versions.RELEASES_URL)
        QDesktopServices.openUrl(url)

    def _restart(self) -> None:
        """Start the new version and leave."""
        argv = updater.restart_command()
        self._log_line("Restarting: " + " ".join(argv))
        # PyQt returns (started, pid) for the static overload on some builds
        # and a plain bool on others; both answers are read the same way here.
        answer = QProcess.startDetached(argv[0], argv[1:],
                                        os.path.expanduser("~"))
        started = answer[0] if isinstance(answer, tuple) else bool(answer)
        if not started:
            QMessageBox.warning(
                self, "LinRAR Update",
                "LinRAR could not start the new version by itself.\n\n"
                "Close LinRAR and open it again to use " +
                (self.update.version if self.update else "the update") + ".",
            )
            return
        self.accept()
        QApplication.quit()

    # -- closing -----------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._installing and self.task is not None:
            answer = QMessageBox.question(
                self, "LinRAR Update",
                "The update is still being installed.\n\n"
                "Stopping now puts the previous version back. Stop it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.task.cancel()
            self._log_line("Stopping; the previous version will be put back.")
            event.ignore()
            return
        if self.task is not None:
            # Waiting here would freeze the interface for as long as a stuck
            # socket takes to time out.  The worker is asked to stop, cut loose
            # from this window, and left to finish into nothing.
            self.task.cancel()
            try:
                self.task.disconnect()
            except TypeError:      # nothing was connected
                pass
            self.task = None
        super().closeEvent(event)

    def reject(self) -> None:
        # Cancel is the same door as the window's close button.
        if self._installing:
            self.close()
            return
        super().reject()


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{minutes // 60} hour{'s' if minutes // 60 != 1 else ''}"


def _mono() -> QFont:
    font = QFont("monospace")
    font.setStyleHint(QFont.StyleHint.TypeWriter)
    font.setPointSize(max(8, QApplication.font().pointSize() - 1))
    return font


# --------------------------------------------------------------- entry points


def open_updater(parent, auto_install: bool = False) -> UpdateDialog:
    """Help > Check for updates: open the window and start looking."""
    dialog = UpdateDialog(parent, auto_install=auto_install)
    dialog.start_check()
    dialog.exec()
    return dialog


def due_for_check(now: Optional[float] = None) -> bool:
    """Has enough time passed since the last start-up check?"""
    if START_CHECK_INTERVAL <= 0:
        return True
    stamp = str(SETTINGS.get("update/last_check") or "")
    if not stamp:
        return True
    try:
        last = time.mktime(time.strptime(stamp, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return True
    return (now or time.time()) - last >= START_CHECK_INTERVAL


class StartupCheck:
    """The quiet check that runs when LinRAR opens.

    It is quiet in that nothing appears unless there is something to say: no
    window while it asks, no window if the answer is "you are up to date", and
    no window if the server cannot be reached; a failed update check is not
    the user's problem and must never be the first thing they see.

    When there *is* an update, what happens next is what the user asked for in
    Settings: it is either offered, or installed with the window showing every
    stage of it.
    """

    def __init__(self, window) -> None:
        self.window = window
        self.task: Optional[UpdateTask] = None

    @staticmethod
    def wanted() -> bool:
        return bool(SETTINGS.get("update/check_on_start")
                    or SETTINGS.get("update/automatic"))

    def schedule(self) -> None:
        """Arrange the check for shortly after the window has settled."""
        if not self.wanted() or not updater.eligibility():
            return
        # An update applied earlier in this session is already on disk; asking
        # the server again before the restart would only offer what is already
        # installed.
        if versions.restart_pending():
            return
        if not due_for_check():
            return
        QTimer.singleShot(START_CHECK_DELAY_MS, self.run)

    def run(self) -> None:
        allow_pre = bool(SETTINGS.get("update/prereleases"))
        self.task = UpdateTask(
            lambda ctx: updater.check(ctx, allow_prerelease=allow_pre),
            install=False,
        )
        _keep(self.task)
        self.task.checked.connect(self._found)
        # Deliberately not connected to anything that shows: an update check
        # that failed in the background is a log line, not an interruption.
        self.task.failed.connect(self._quiet_failure)
        self.task.start()
        SETTINGS.set("update/last_check", time.strftime("%Y-%m-%dT%H:%M:%S"))

    def _quiet_failure(self, error: Exception) -> None:
        self.task = None
        message = getattr(error, "message", str(error))
        try:
            self.window.statusBar().showMessage(
                f"Could not check for updates: {message}", 6000
            )
        except Exception:  # pragma: no cover - the window may be closing
            pass

    def _found(self, found: Optional[Update]) -> None:
        self.task = None
        if found is None:
            return
        if str(SETTINGS.get("update/skipped") or "") == found.version:
            return

        automatic = bool(SETTINGS.get("update/automatic"))
        dialog = UpdateDialog(self.window, auto_install=automatic)
        dialog.update = found
        dialog.present(found)
        dialog.exec()
