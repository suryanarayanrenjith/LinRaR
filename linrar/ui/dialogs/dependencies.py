"""The Dependencies manager: install and remove the tools the app drives."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ...core import elevation, packages
from ...core.backends.base import TaskContext
from ...core.models import OperationError
from ...core.process import ProcessRunner
from ...core.registry import REGISTRY
from ...core.settings import SETTINGS
from ...core.tasks import Task
from .. import icons, theme

_DEP_ROLE = Qt.ItemDataRole.UserRole


class DependenciesDialog(QDialog):
    """Shows every external tool, its state, and lets the user manage it.

    Installation runs the distribution's own package manager through ``pkexec``
    so the desktop's authentication dialog handles the privilege prompt.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dependencies")
        self.setWindowIcon(icons.icon("package"))
        self.resize(740, 640)

        self.manager = packages.detect_manager()
        self._task: Optional[Task] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_table(), 1)
        layout.addLayout(self._build_buttons())
        layout.addWidget(self._build_log(), 0)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self.refresh()

    # -- construction ------------------------------------------------------

    def _build_header(self) -> QGroupBox:
        group = QGroupBox("System")
        box = QVBoxLayout(group)
        box.setSpacing(4)

        distro = QLabel(f"<b>Distribution:</b> {packages.distro_name()}")
        box.addWidget(distro)

        if self.manager is not None:
            manager_text = f"<b>Package manager:</b> {self.manager.label}"
        else:
            manager_text = (
                "<b>Package manager:</b> not detected — install the tools "
                "manually."
            )
        manager_label = QLabel(manager_text)
        if self.manager is None:
            manager_label.setObjectName("Failure")
        box.addWidget(manager_label)

        admin_row = QHBoxLayout()
        admin_row.setSpacing(8)
        self.admin_icon = QLabel()
        self.admin_icon.setPixmap(icons.pixmap("lock", 20))
        admin_row.addWidget(self.admin_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self.admin_label = QLabel()
        self.admin_label.setWordWrap(True)
        admin_row.addWidget(self.admin_label, 1)

        self.admin_button = QPushButton("Get administrator access")
        self.admin_button.setIcon(icons.icon("key"))
        self.admin_button.clicked.connect(self._request_admin)
        admin_row.addWidget(self.admin_button, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(admin_row)

        self._refresh_admin_state()
        return group

    # -- administrator access ---------------------------------------------

    def _refresh_admin_state(self) -> None:
        session = elevation.SESSION
        self.admin_label.setText(session.describe(self._method_preference()))
        granted = elevation.is_root() or session.active
        self.admin_icon.setPixmap(
            icons.pixmap("key" if granted else "lock", 20)
        )
        self.admin_label.setObjectName("Success" if granted else "")
        self.admin_label.style().unpolish(self.admin_label)
        self.admin_label.style().polish(self.admin_label)
        self.admin_button.setEnabled(
            not elevation.is_root()
            and bool(elevation.available())
            and not session.active
        )
        self.admin_button.setText(
            "Administrator access held" if session.active
            else "Get administrator access"
        )

    @staticmethod
    def _method_preference() -> str:
        return str(SETTINGS.get("admin/method") or "auto")

    def _request_admin(self) -> bool:
        """Authenticate once so the operations that follow just run."""
        session = elevation.SESSION
        preference = self._method_preference()
        if elevation.is_root() or session.active:
            self._refresh_admin_state()
            return True

        password = None
        if session.needs_password(preference):
            method = session.preferred(preference)
            password, ok = QInputDialog.getText(
                self,
                "Administrator access",
                f"LinRAR needs administrator rights to install or remove "
                f"packages.\n\nEnter your password for "
                f"{method.binary if method else 'sudo'}:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return False

        ok, message = session.authenticate(password, preference)
        password = None  # not kept a moment longer than needed
        self._refresh_admin_state()
        if not ok:
            QMessageBox.warning(self, "Administrator access", message)
        else:
            self._append_log(f"--- {message} ---")
        return ok

    def _build_table(self) -> QTreeWidget:
        self.table = QTreeWidget()
        self.table.setColumnCount(5)
        self.table.setHeaderLabels(
            ["Component", "Status", "Version", "Package", "Location"]
        )
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(False)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.itemSelectionChanged.connect(self._on_selection)
        header = self.table.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 150)
        self.table.setMinimumHeight(190)
        return self.table

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.install_button = QPushButton("Install")
        self.install_button.setIcon(icons.icon("download"))
        self.install_button.clicked.connect(self._install_selected)

        self.remove_button = QPushButton("Uninstall")
        self.remove_button.setIcon(icons.icon("trash"))
        self.remove_button.clicked.connect(self._remove_selected)

        self.install_all_button = QPushButton("Install all missing")
        self.install_all_button.setIcon(icons.icon("package"))
        self.install_all_button.clicked.connect(self._install_all_missing)

        refresh_button = QPushButton("Refresh")
        refresh_button.setIcon(icons.icon("refresh"))
        refresh_button.clicked.connect(self.refresh)

        for button in (
            self.install_button,
            self.remove_button,
            self.install_all_button,
            refresh_button,
        ):
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _build_log(self) -> QGroupBox:
        group = QGroupBox("Details")
        box = QVBoxLayout(group)

        self.detail_label = QLabel("Select a component to see what it does.")
        self.detail_label.setWordWrap(True)
        box.addWidget(self.detail_label)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("monospace", 8))
        self.log.setMaximumHeight(120)
        self.log.setPlaceholderText("Package manager output appears here.")
        box.addWidget(self.log)
        return group

    # -- state -------------------------------------------------------------

    def refresh(self) -> None:
        """Re-probe every dependency and repaint the table."""
        selected_key = None
        if current := self.table.currentItem():
            selected_key = current.data(0, _DEP_ROLE)

        self.table.clear()
        for status in packages.all_statuses():
            dependency = status.dependency
            names = dependency.packages_for(self.manager)
            item = QTreeWidgetItem(
                self.table,
                [
                    dependency.name,
                    "Installed" if status.installed else (
                        "Missing" if dependency.essential else "Not installed"
                    ),
                    status.version or ("-" if status.installed else ""),
                    " ".join(names) if names else "-",
                    status.path or "",
                ],
            )
            item.setData(0, _DEP_ROLE, dependency.key)
            item.setIcon(0, icons.icon("package"))
            if status.installed:
                item.setForeground(1, QColor(theme.current().ok))
            elif dependency.essential:
                item.setForeground(1, QColor(theme.current().error))
            else:
                item.setForeground(1, QColor(theme.current().warn))
            if selected_key == dependency.key:
                self.table.setCurrentItem(item)

        if self.table.currentItem() is None and self.table.topLevelItemCount():
            self.table.setCurrentItem(self.table.topLevelItem(0))
        self._on_selection()
        if hasattr(self, "admin_label"):
            self._refresh_admin_state()

        # Backends cache which binaries they found at construction time, so
        # they must re-probe after anything is installed or removed.
        REGISTRY.refresh()

    def _selected(self) -> Optional[packages.DependencyStatus]:
        item = self.table.currentItem()
        if item is None:
            return None
        key = item.data(0, _DEP_ROLE)
        for dependency in packages.DEPENDENCIES:
            if dependency.key == key:
                return packages.dependency_status(dependency)
        return None

    def _on_selection(self) -> None:
        status = self._selected()
        if status is None:
            self.install_button.setEnabled(False)
            self.remove_button.setEnabled(False)
            return

        dependency = status.dependency
        text = dependency.description
        if note := dependency.note_for(self.manager):
            text += f"\n\nNote: {note}"
        if not dependency.packages_for(self.manager) and self.manager is not None:
            text += (
                f"\n\nThis component has no package for "
                f"{self.manager.label} and must be installed manually."
            )
        self.detail_label.setText(text)

        can_manage = bool(dependency.packages_for(self.manager))
        self.install_button.setEnabled(can_manage and not status.installed)
        self.remove_button.setEnabled(can_manage and status.installed)

    # -- actions -----------------------------------------------------------

    def _install_selected(self) -> None:
        status = self._selected()
        if status is None:
            return
        names = status.dependency.packages_for(self.manager)
        if not names or self.manager is None:
            return
        self._run_package_command(
            self.manager.install_command(names),
            f"Installing {status.dependency.name}",
        )

    def _remove_selected(self) -> None:
        status = self._selected()
        if status is None or self.manager is None:
            return
        names = status.dependency.packages_for(self.manager)
        if not names:
            return
        reply = QMessageBox.question(
            self,
            "Uninstall",
            f"Remove {status.dependency.name} ({' '.join(names)})?\n\n"
            + (
                "This component is required for core features and archives "
                "will stop working without it."
                if status.dependency.essential
                else "Some archive formats will stop working."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_package_command(
            self.manager.remove_command(names),
            f"Removing {status.dependency.name}",
        )

    def _install_all_missing(self) -> None:
        if self.manager is None:
            return
        names: list[str] = []
        for status in packages.all_statuses():
            if status.installed:
                continue
            names.extend(status.dependency.packages_for(self.manager))
        if not names:
            QMessageBox.information(
                self, "Dependencies", "Everything is already installed."
            )
            return
        self._run_package_command(
            self.manager.install_command(names), "Installing missing components"
        )

    def _run_package_command(self, argv: list[str], title: str) -> None:
        """Run a package manager command with root rights, streaming output."""
        preference = self._method_preference()
        # Ask for the password up front rather than letting the command fail:
        # there is no terminal for sudo to prompt on.
        if elevation.SESSION.needs_password(preference):
            if not self._request_admin():
                self._append_log(f"--- {title}: cancelled ---")
                return

        elevated = packages.privileged(argv, preference)
        if elevated is None:
            QMessageBox.information(
                self,
                "Administrator rights required",
                "This change needs administrator rights, but no way to obtain "
                "them was found.\n\nRun this in a terminal instead:\n\n"
                + packages.manual_instructions(argv),
            )
            self.log.appendPlainText("$ " + packages.manual_instructions(argv))
            return

        self.log.clear()
        self.log.appendPlainText("$ " + " ".join(elevated))
        self._set_busy(True)

        def work(ctx: TaskContext):
            runner = ProcessRunner(elevated, on_line=ctx.on_message)
            ctx.attach(runner)
            try:
                code = runner.run()
            finally:
                ctx.detach()
            if code != 0:
                raise OperationError(
                    _explain(code, runner.output), code, runner.output
                )
            return runner.output

        task = Task(work, title, self)
        self._task = task
        task.messageLogged.connect(self._append_log)
        task.succeeded.connect(lambda _r: self._on_done(title, None))
        task.failed.connect(lambda err: self._on_done(title, err))
        task.start()

    def _append_log(self, line: str) -> None:
        self.log.appendPlainText(line)
        self.log.verticalScrollBar().setValue(
            self.log.verticalScrollBar().maximum()
        )

    def _on_done(self, title: str, error: Optional[OperationError]) -> None:
        self._set_busy(False)
        self.refresh()
        if error is None:
            self._append_log(f"--- {title}: finished successfully ---")
            QMessageBox.information(self, "Dependencies", f"{title}: done.")
        else:
            self._append_log(f"--- {title}: failed ---")
            QMessageBox.critical(self, "Dependencies", error.message)
        self._task = None

    def _set_busy(self, busy: bool) -> None:
        for button in (
            self.install_button,
            self.remove_button,
            self.install_all_button,
        ):
            button.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.setCursor(
            Qt.CursorShape.WaitCursor if busy else Qt.CursorShape.ArrowCursor
        )
        if not busy:
            self._on_selection()

    def closeEvent(self, event) -> None:
        if self._task is not None and self._task.isRunning():
            QMessageBox.information(
                self,
                "Dependencies",
                "Please wait for the current operation to finish.",
            )
            event.ignore()
            return
        super().closeEvent(event)


def _explain(code: int, output: str) -> str:
    """Turn a package manager failure into something actionable."""
    lowered = output.lower()
    if code == 126 or "dismissed" in lowered or "not authorized" in lowered:
        return (
            "The operation was cancelled or authentication failed.\n\n"
            "Administrator rights are required to change installed packages."
        )
    if "unable to locate package" in lowered or "no match for argument" in lowered:
        return (
            "The package was not found in the configured repositories.\n\n"
            "It may live in an optional repository that needs enabling first "
            "(for example 'multiverse' on Ubuntu, or RPM Fusion on Fedora)."
        )
    if "could not get lock" in lowered or "another process" in lowered:
        return (
            "Another package operation is already running.\n\n"
            "Wait for it to finish and try again."
        )
    detail = "\n".join(
        line for line in output.splitlines()[-6:] if line.strip()
    )
    return f"The package manager failed (exit code {code})." + (
        f"\n\n{detail}" if detail else ""
    )
