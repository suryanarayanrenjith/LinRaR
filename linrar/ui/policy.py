"""Showing the administrator's settings, and their locks, in the interface.

The system-wide layer is described in :mod:`linrar.core.settings`.  Whatever it
locks must look locked: a control the user can still click, but that quietly
refuses to save, is worse than no control at all.  Everything here is about
making that visible in one consistent way: the control is disabled, its
tooltip says who decided, and the dialog carries a banner naming the file.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from ..core.settings import SETTINGS, Settings
from . import icons


def _store(settings: Settings | None) -> Settings:
    return settings if settings is not None else SETTINGS


def guard(widget: QWidget, key: str, settings: Settings | None = None) -> bool:
    """Disable *widget* if *key* is locked.  Returns whether it is.

    The tooltip is replaced rather than appended to: a disabled control's own
    explanation of what it would do is no longer the useful thing to read.
    """
    store = _store(settings)
    if not store.is_locked(key):
        return False
    widget.setEnabled(False)
    widget.setToolTip(store.lock_reason(key))
    return True


def guard_all(
    pairs: dict[str, QWidget] | list[tuple[str, QWidget]],
    settings: Settings | None = None,
) -> list[str]:
    """Guard many controls at once; returns the keys that turned out locked."""
    items = pairs.items() if isinstance(pairs, dict) else pairs
    return [key for key, widget in items if guard(widget, key, settings)]


def guard_actions(
    pairs: dict[str, object] | list[tuple[str, object]],
    settings: Settings | None = None,
) -> list[str]:
    """The same for QAction, which is not a QWidget but disables identically."""
    store = _store(settings)
    items = pairs.items() if isinstance(pairs, dict) else pairs
    locked = []
    for key, action in items:
        if action is None or not store.is_locked(key):
            continue
        action.setEnabled(False)
        action.setToolTip(store.lock_reason(key))
        locked.append(key)
    return locked


def summary(settings: Settings | None = None) -> str:
    """One sentence naming where the system-wide settings come from."""
    store = _store(settings)
    system = store.system
    if not system.files:
        return "No system-wide configuration is installed."
    files = ", ".join(system.files)
    keys = len(system.values)
    locked = len(system.locked_keys())
    sentence = (
        f"{keys} setting{'' if keys == 1 else 's'} for every user of this "
        f"machine come from {files}."
    )
    if locked:
        sentence += (
            f"  {locked} of them {'is' if locked == 1 else 'are'} locked and "
            "cannot be changed here."
        )
    return sentence


class LockBanner(QWidget):
    """A line at the top of a dialog: some of this is not yours to change."""

    def __init__(self, locked: list[str], parent=None,
                 settings: Settings | None = None) -> None:
        super().__init__(parent)
        store = _store(settings)
        # A plain QWidget only paints a stylesheet background once it is told
        # to; without this the card would be an invisible one.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("lock", 16))
        glyph.setFixedWidth(18)
        layout.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)

        count = len(locked)
        where = store.system.source_file(locked[0]) if locked else ""
        text = QLabel(
            f"<b>{count} of the settings in this window "
            f"{'is' if count == 1 else 'are'} managed by your system "
            f"administrator.</b> Those are shown greyed out; everything else "
            "is yours to change."
            + (f"<br><span>{where}</span>" if where else "")
        )
        text.setWordWrap(True)
        text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        text.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        layout.addWidget(text, 1)
        self.setObjectName("Card")
        self.setToolTip(
            "Locked settings:\n  " + "\n  ".join(locked)
            + (f"\n\nfrom {where}" if where else "")
        )


def banner(locked: list[str], parent=None,
           settings: Settings | None = None) -> LockBanner | None:
    """A :class:`LockBanner` when something is locked, otherwise nothing."""
    if not locked:
        return None
    return LockBanner(locked, parent, settings)
