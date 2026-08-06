"""LinRAR for Linux: a WinRAR-style archive manager.

Importing the package gives you the version and nothing else: everything
graphical lives under :mod:`linrar.ui` and is imported only once the platform
check in :mod:`linrar.core.platform` has passed.  That is what lets an updater,
a packaging script or ``python -c "import linrar; print(linrar.__version__)"``
ask which version is installed on a machine with no display and no PyQt6.
"""

from .version import VERSION, __version__

__all__ = ["VERSION", "__version__"]
