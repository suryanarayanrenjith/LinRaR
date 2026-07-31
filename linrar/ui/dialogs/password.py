"""Password entry, matching WinRAR's "Enter password" dialog."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from .. import icons


class PasswordDialog(QDialog):
    """Ask for a password.

    In *confirm* mode (used when creating an archive) a second field appears
    along with the header-encryption option, exactly as WinRAR does.
    """

    def __init__(
        self,
        parent=None,
        archive_name: str = "",
        confirm: bool = False,
        encrypt_headers: bool = False,
        allow_header_encryption: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Enter password")
        self.setWindowIcon(icons.icon("key"))
        self.setModal(True)
        self._confirm = confirm

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)

        if archive_name:
            header = QLabel(f"Enter password for the archive\n{archive_name}")
            header.setWordWrap(True)
            layout.addWidget(header)

        group = QGroupBox("Enter password")
        form = QFormLayout(group)
        form.setContentsMargins(10, 10, 10, 10)
        form.setSpacing(7)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setMinimumWidth(240)
        form.addRow("Enter password", self.password_edit)

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
        if confirm:
            form.addRow("Reenter password for verification", self.confirm_edit)

        self.show_check = QCheckBox("Show password")
        self.show_check.toggled.connect(self._toggle_echo)
        form.addRow("", self.show_check)

        self.header_check = QCheckBox("Encrypt file names")
        self.header_check.setChecked(encrypt_headers and allow_header_encryption)
        self.header_check.setToolTip(
            "Also encrypt the list of files, so the archive contents cannot be "
            "seen without the password."
        )
        if confirm:
            form.addRow("", self.header_check)
            if not allow_header_encryption:
                self.header_check.setEnabled(False)
                self.header_check.setToolTip(
                    "ZIP archives cannot encrypt their file names; choose RAR "
                    "or 7z for that."
                )

        layout.addWidget(group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.password_edit.setFocus()

    def _toggle_echo(self, shown: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self.password_edit.setEchoMode(mode)
        self.confirm_edit.setEchoMode(mode)

    def _accept(self) -> None:
        if self._confirm:
            if not self.password_edit.text():
                QMessageBox.warning(self, "LinRAR", "Please enter a password.")
                return
            if self.password_edit.text() != self.confirm_edit.text():
                QMessageBox.warning(
                    self, "LinRAR", "The passwords you entered do not match."
                )
                self.confirm_edit.clear()
                self.confirm_edit.setFocus()
                return
        self.accept()

    @property
    def password(self) -> str:
        return self.password_edit.text()

    @property
    def encrypt_headers(self) -> bool:
        return self.header_check.isChecked()

    @staticmethod
    def ask(
        parent,
        archive_name: str = "",
        confirm: bool = False,
        allow_header_encryption: bool = True,
    ) -> Optional[tuple[str, bool]]:
        """Return ``(password, encrypt_headers)`` or ``None`` if cancelled."""
        dialog = PasswordDialog(
            parent,
            archive_name,
            confirm,
            allow_header_encryption=allow_header_encryption,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.password, dialog.encrypt_headers
        return None
