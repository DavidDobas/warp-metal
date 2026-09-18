"""Build a warp-metal wheel from the Warp fork and test it in a clean environment.

Usage:
    python tools/release.py <fork checkout> --revision NN [--skip-build] [--publish]

Steps: download the stock ``warp-lang`` wheel of the fork's version, build the core library in the
fork, generate the overlay (``tools/generate.py``), build the wheel, install it next to the stock
package in a fresh virtual environment and run ``tools/smoke_test.py``. With ``--publish`` the wheel
is then attached to a GitHub prerelease named after its version. Needs macOS on Apple Silicon, ``uv``
and, for ``--publish``, ``gh``.
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NVIDIA_INDEX = "https://pypi.nvidia.com"  # nightlies; releases come from PyPI


def run(cmd, cwd=None):
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=cwd)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fork", help="checkout of https://github.com/DavidDobas/warp at the commit to release")
    ap.add_argument("--revision", required=True, help="two digits; start at 01 for each Warp version")
    ap.add_argument("--skip-build", action="store_true", help="use the fork's existing warp/bin/libwarp.dylib")
    ap.add_argument("--publish", action="store_true", help="create the GitHub prerelease and upload the wheel")
    args = ap.parse_args()
    fork = os.path.abspath(args.fork)
    warp_version = open(os.path.join(fork, "VERSION.md")).read().strip()

    with tempfile.TemporaryDirectory() as tmp:
        # stock wheel: what the overlay is compared against and what users will have installed
        run(
            ["uvx", "pip", "download", "--no-deps", "--only-binary=:all:", "--platform", "macosx_11_0_arm64",
             "--python-version", "3.12", "--extra-index-url", NVIDIA_INDEX, f"warp-lang=={warp_version}", "-d", tmp]
        )  # fmt: skip
        stock = os.path.join(tmp, "stock")
        with zipfile.ZipFile(glob.glob(os.path.join(tmp, "warp_lang-*.whl"))[0]) as wheel:
            wheel.extractall(stock)

        if not args.skip_build:
            run(["uv", "run", "build_lib.py"], cwd=fork)
        run([sys.executable, os.path.join(ROOT, "tools", "generate.py"), fork, "--stock", stock,
             "--revision", args.revision])  # fmt: skip

        shutil.rmtree(os.path.join(ROOT, "dist"), ignore_errors=True)
        run(["uv", "build", "--wheel"], cwd=ROOT)
        (wheel_path,) = glob.glob(os.path.join(ROOT, "dist", "warp_metal-*.whl"))

        # clean environment, run from outside both source trees
        env = os.path.join(tmp, "env")
        run(["uv", "venv", "--python", "3.12", env])
        python = os.path.join(env, "bin", "python")
        run(["uv", "pip", "install", "--python", python, "--prerelease", "allow", "--index-strategy",
             "unsafe-best-match", "--extra-index-url", NVIDIA_INDEX, wheel_path])  # fmt: skip
        run([python, os.path.join(ROOT, "tools", "smoke_test.py")], cwd=tmp)

    print(f"\nbuilt and tested {wheel_path}")
    if args.publish:
        version = os.path.basename(wheel_path).split("-")[1]
        target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        run(["gh", "release", "create", f"v{version}", wheel_path, "--prerelease", "--target", target,
             "--title", f"warp-metal {version}",
             "--notes", f"Overlays warp-lang {warp_version}. Built from the Warp fork at "
             f"https://github.com/DavidDobas/warp/commit/{fork_commit(fork)}."], cwd=ROOT)  # fmt: skip


def fork_commit(fork):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fork, text=True).strip()


if __name__ == "__main__":
    main()
