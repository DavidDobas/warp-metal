"""Install the import hook that overlays Warp's modules with their Metal-capable versions.

Executed at interpreter start from ``warp_metal_boot.pth`` (before any ``import warp``), so the
hook is in place when Warp's package initializes. The overlay only engages when the installed
``warp-lang`` is exactly the version it was generated for; otherwise Warp loads unmodified and
``status()`` explains why. Set ``WARP_METAL_DISABLE=1`` to keep the overlay off.
"""

import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys

try:
    from warp_metal._generated import (
        FORK_COMMIT,
        OVERLAY_MODULES,
        REQUIRED_WARP_VERSION,
    )
except (
    ImportError
):  # a source checkout: the overlay is generated at release time (tools/release.py)
    FORK_COMMIT, OVERLAY_MODULES, REQUIRED_WARP_VERSION = None, [], None

_HERE = os.path.dirname(os.path.abspath(__file__))
_OVERLAY_DIR = os.path.join(_HERE, "_overlay")
_state = {"active": False, "reason": "not initialized", "checked": False}


def _installed_warp_version():
    try:
        from importlib.metadata import version

        return version("warp-lang")
    except Exception:  # noqa: BLE001
        return None


def _engage():
    """Decide once whether the overlay applies to the installed Warp."""
    if _state["checked"]:
        return _state["active"]
    _state["checked"] = True
    if os.environ.get("WARP_METAL_DISABLE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        _state["reason"] = "disabled by WARP_METAL_DISABLE"
        return False
    if REQUIRED_WARP_VERSION is None:
        _state["reason"] = (
            "this is a source checkout without the generated overlay; install a released wheel"
        )
        return False
    if sys.platform != "darwin":
        _state["reason"] = f"platform {sys.platform} is not macOS"
        return False
    installed = _installed_warp_version()
    if installed != REQUIRED_WARP_VERSION:
        _state["reason"] = (
            f"warp-lang {installed} is installed but this warp-metal build overlays warp-lang "
            f"{REQUIRED_WARP_VERSION}; install the matching version (or a matching warp-metal release)"
        )
        print(f"[warp-metal] not active: {_state['reason']}", file=sys.stderr)
        return False
    _state["active"] = True
    _state["reason"] = "active"
    return True


class _Loader(importlib.machinery.SourceFileLoader):
    def exec_module(self, module):
        super().exec_module(module)
        if module.__name__ == "warp._src.context":
            # the fork exports this from warp/__init__.py; the stock package does not
            warp_pkg = sys.modules.get("warp")
            if warp_pkg is not None and hasattr(module, "is_metal_available"):
                warp_pkg.is_metal_available = module.is_metal_available


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if not fullname.startswith("warp._src."):
            return None
        name = fullname[len("warp._src.") :]
        if name not in OVERLAY_MODULES or not _engage():
            return None
        file = os.path.join(_OVERLAY_DIR, name + ".py")
        return importlib.util.spec_from_file_location(
            fullname, file, loader=_Loader(fullname, file)
        )


def status():
    """Return ``(active, reason)`` for the overlay."""
    _engage()
    return _state["active"], _state["reason"]


if not any(isinstance(f, _Finder) for f in sys.meta_path):
    sys.meta_path.insert(0, _Finder())
