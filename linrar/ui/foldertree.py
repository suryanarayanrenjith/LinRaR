"""The optional left-hand folder tree (WinRAR's "Folders" pane)."""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from . import icons

_PATH_ROLE = Qt.ItemDataRole.UserRole
_LOADED_ROLE = Qt.ItemDataRole.UserRole + 1


class FolderTree(QTreeWidget):
    """Shows disk folders, or the folder structure inside the open archive.

    Disk branches are filled in on expand so opening a deep home directory stays
    instant.
    """

    folderSelected = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIconSize(_size(16))
        self.setAnimated(False)
        self.setExpandsOnDoubleClick(True)
        self._archive_mode = False
        self._suppress = False

        self.itemExpanded.connect(self._on_expanded)
        self.itemSelectionChanged.connect(self._on_selection)

    # -- disk mode ---------------------------------------------------------

    def show_filesystem(self, current: str = "") -> None:
        self._archive_mode = False
        self._suppress = True
        self.clear()

        root = QTreeWidgetItem(self, ["/"])
        root.setIcon(0, icons.icon("disk"))
        root.setData(0, _PATH_ROLE, "/")
        root.setData(0, _LOADED_ROLE, False)
        root.setChildIndicatorPolicy(
            QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
        )

        home = os.path.expanduser("~")
        home_item = QTreeWidgetItem(self, [os.path.basename(home) or "home"])
        home_item.setIcon(0, icons.icon("folder"))
        home_item.setData(0, _PATH_ROLE, home)
        home_item.setData(0, _LOADED_ROLE, False)
        home_item.setChildIndicatorPolicy(
            QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
        )

        self._suppress = False
        if current:
            self.reveal(current)
        else:
            self.expandItem(home_item)

    def _populate(self, item: QTreeWidgetItem) -> None:
        if item.data(0, _LOADED_ROLE):
            return
        item.setData(0, _LOADED_ROLE, True)
        path = item.data(0, _PATH_ROLE)
        if not path or not os.path.isdir(path):
            return
        try:
            names = sorted(
                (e for e in os.scandir(path) if e.is_dir(follow_symlinks=False)),
                key=lambda e: e.name.lower(),
            )
        except OSError:
            return
        for entry in names:
            if entry.name.startswith("."):
                continue
            child = QTreeWidgetItem(item, [entry.name])
            child.setIcon(0, icons.icon("folder"))
            child.setData(0, _PATH_ROLE, entry.path)
            child.setData(0, _LOADED_ROLE, False)
            if _has_subdirs(entry.path):
                child.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                )
            else:
                child.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator
                )

    def reveal(self, path: str) -> None:
        """Expand down to *path* and select it."""
        if self._archive_mode:
            return
        path = os.path.abspath(path)
        self._suppress = True
        try:
            home = os.path.expanduser("~")
            if path == home or path.startswith(home + os.sep):
                root = self.topLevelItem(1)
                base = home
            else:
                root = self.topLevelItem(0)
                base = "/"
            if root is None:
                return
            self._populate(root)
            root.setExpanded(True)

            remainder = os.path.relpath(path, base)
            node = root
            if remainder not in (".", ""):
                for part in remainder.split(os.sep):
                    self._populate(node)
                    node.setExpanded(True)
                    match = None
                    for i in range(node.childCount()):
                        if node.child(i).text(0) == part:
                            match = node.child(i)
                            break
                    if match is None:
                        break
                    node = match
            self._populate(node)
            self.setCurrentItem(node)
            self.scrollToItem(node)
        finally:
            self._suppress = False

    # -- archive mode ------------------------------------------------------

    def show_archive(self, archive_name: str, folders: list[str]) -> None:
        """Render the archive's internal folder structure."""
        self._archive_mode = True
        self._suppress = True
        self.clear()

        root = QTreeWidgetItem(self, [archive_name])
        root.setIcon(0, icons.icon("archive-small"))
        root.setData(0, _PATH_ROLE, "")
        nodes: dict[str, QTreeWidgetItem] = {"": root}

        for folder in sorted(set(folders)):
            if not folder:
                continue
            parts = folder.split("/")
            for depth in range(1, len(parts) + 1):
                key = "/".join(parts[:depth])
                if key in nodes:
                    continue
                parent_key = "/".join(parts[: depth - 1])
                parent = nodes.get(parent_key, root)
                node = QTreeWidgetItem(parent, [parts[depth - 1]])
                node.setIcon(0, icons.icon("folder"))
                node.setData(0, _PATH_ROLE, key)
                nodes[key] = node

        root.setExpanded(True)
        self.setCurrentItem(root)
        self._suppress = False

    def select_archive_folder(self, folder: str) -> None:
        if not self._archive_mode:
            return
        self._suppress = True
        try:
            match = self._find_by_path(self.invisibleRootItem(), folder)
            if match is not None:
                parent = match.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.setCurrentItem(match)
                self.scrollToItem(match)
        finally:
            self._suppress = False

    def _find_by_path(
        self, node: QTreeWidgetItem, target: str
    ) -> Optional[QTreeWidgetItem]:
        for i in range(node.childCount()):
            child = node.child(i)
            if child.data(0, _PATH_ROLE) == target:
                return child
            found = self._find_by_path(child, target)
            if found is not None:
                return found
        return None

    # -- events ------------------------------------------------------------

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        if not self._archive_mode:
            self._populate(item)

    def _on_selection(self) -> None:
        if self._suppress:
            return
        item = self.currentItem()
        if item is None:
            return
        path = item.data(0, _PATH_ROLE)
        if path is not None:
            self.folderSelected.emit(path)


def _has_subdirs(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                    return True
    except OSError:
        return False
    return False


def _size(value: int):
    from PyQt6.QtCore import QSize

    return QSize(value, value)
