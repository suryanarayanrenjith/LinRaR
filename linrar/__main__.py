"""Allows ``python -m linrar``."""

from .core.platform import ensure_supported

# Before anything graphical is imported: a system LinRAR does not support is
# also one where PyQt6 may not import at all, and this explains itself better
# than the traceback would.
ensure_supported()

from .app import main  # noqa: E402  (deliberately after the platform check)

if __name__ == "__main__":
    raise SystemExit(main())
