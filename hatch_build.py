"""Wheel build hook: the wheel carries a macOS arm64 library, and must not be built without the overlay."""

import os

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

REQUIRED = [
    "_generated.py",
    "_overlay/build.py",
    "_overlay/context.py",
    "native/builtin.h",
    "bin/libwarp.dylib",
]


class OverlayBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != "wheel":
            return
        package = os.path.join(self.root, "src", "warp_metal")
        missing = [name for name in REQUIRED if not os.path.exists(os.path.join(package, name))]
        if missing:
            raise RuntimeError(
                "the overlay has not been generated (missing: " + ", ".join(missing) + "); "
                "build wheels with tools/release.py"
            )
        build_data["pure_python"] = False
        # same platform tag as the stock warp-lang wheel this overlays
        build_data["tag"] = "py3-none-macosx_11_0_arm64"
