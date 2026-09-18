"""Apple Metal backend for NVIDIA Warp.

Importing ``warp`` on Apple Silicon with this package installed adds the ``metal:0`` device.
The package overlays the Warp modules that implement the backend and ships the native
runtime; it activates automatically through a ``.pth`` hook, so nothing has to be imported
explicitly. ``warp_metal.status()`` reports whether the overlay is active and why not.
"""

from warp_metal._bootstrap import status, REQUIRED_WARP_VERSION, FORK_COMMIT

__all__ = ["status", "REQUIRED_WARP_VERSION", "FORK_COMMIT"]
