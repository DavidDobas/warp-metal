"""Regenerate the overlay from a checkout of the Warp fork (https://github.com/DavidDobas/warp).

Usage: python tools/generate.py <fork checkout> --warp-version <stock warp-lang version the fork is based on>

Copies the Python modules the fork changes, the native headers Metal and CPU kernels compile
against, and the built core library, then records the fork commit and the required Warp version.
Nothing under src/warp_metal/_overlay, native or bin is edited by hand.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "src", "warp_metal")

# Warp modules the fork changes and that are needed at runtime (git diff --name-only against upstream).
OVERLAY_MODULES = ["build", "builtins", "codegen", "context", "dlpack", "texture", "torch", "types", "utils"]
# Native subdirectories needed to compile CPU and Metal kernels (CUDA-only material is left out).
NATIVE_SUBDIRS = ["nanovdb", "clang"]


def run(cmd, cwd):
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fork")
    ap.add_argument("--warp-version", required=True, help="exact warp-lang version the overlay applies to")
    args = ap.parse_args()
    fork = os.path.abspath(args.fork)
    commit = run(["git", "rev-parse", "HEAD"], fork)
    if run(["git", "status", "--porcelain", "--untracked-files=no"], fork):
        print("warning: the fork checkout has uncommitted changes", file=sys.stderr)

    changed = set(run(["git", "diff", "--name-only", "upstream/main...HEAD"], fork).split("\n")) if _has_upstream(fork) else set()
    for m in OVERLAY_MODULES:
        rel = f"warp/_src/{m}.py"
        if changed and rel not in changed:
            print(f"note: {rel} is not changed in the fork; still copied for consistency")
    # Python overlay
    overlay = os.path.join(PKG, "_overlay")
    shutil.rmtree(overlay, ignore_errors=True)
    os.makedirs(overlay)
    for m in OVERLAY_MODULES:
        shutil.copy2(os.path.join(fork, "warp", "_src", f"{m}.py"), os.path.join(overlay, f"{m}.py"))
    open(os.path.join(overlay, "__init__.py"), "w").write("")
    # native headers
    native_src = os.path.join(fork, "warp", "native")
    native_dst = os.path.join(PKG, "native")
    shutil.rmtree(native_dst, ignore_errors=True)
    os.makedirs(native_dst)
    for name in sorted(os.listdir(native_src)):
        p = os.path.join(native_src, name)
        if os.path.isfile(p) and (name.endswith((".h", ".mm", ".exports")) or name in ("crt.cpp",)):
            shutil.copy2(p, native_dst)
    for sub in NATIVE_SUBDIRS:
        shutil.copytree(os.path.join(native_src, sub), os.path.join(native_dst, sub), ignore=shutil.ignore_patterns("*.o", "*.cu"))
    # core library (built in the fork with `uv run build_lib.py`); the LLVM helper comes from stock warp-lang
    bin_dst = os.path.join(PKG, "bin")
    shutil.rmtree(bin_dst, ignore_errors=True)
    os.makedirs(bin_dst)
    shutil.copy2(os.path.join(fork, "warp", "bin", "libwarp.dylib"), bin_dst)
    # metadata
    with open(os.path.join(PKG, "_generated.py"), "w") as f:
        f.write('"""Written by tools/generate.py; do not edit."""\n\n')
        f.write(f'FORK_COMMIT = "{commit}"\n')
        f.write(f'REQUIRED_WARP_VERSION = "{args.warp_version}"\n')
        f.write(f"OVERLAY_MODULES = {OVERLAY_MODULES!r}\n")
    pyproject = os.path.join(ROOT, "pyproject.toml")
    s = open(pyproject).read()
    s = re.sub(r'"warp-lang==[^"]+"', f'"warp-lang=={args.warp_version}"', s)
    open(pyproject, "w").write(s)
    print(f"generated from fork commit {commit[:12]} for warp-lang {args.warp_version}")


def _has_upstream(fork):
    try:
        run(["git", "rev-parse", "--verify", "upstream/main"], fork)
        return True
    except subprocess.CalledProcessError:
        return False


if __name__ == "__main__":
    main()
