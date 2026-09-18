"""Generate the overlay from a checkout of the Warp fork (https://github.com/DavidDobas/warp).

Usage:
    python tools/generate.py <fork checkout> --stock <unpacked stock warp-lang wheel> [--revision NN]

The stock wheel is the source of truth for what has to be overlaid: every Python module under
``warp/_src`` that differs between the fork and the stock package is copied, and the generator
refuses to continue when the two do not belong together. It writes, under ``src/warp_metal``:

    _overlay/       the fork's versions of the modules that differ from stock
    native/         the headers that CPU and Metal kernels compile against
    bin/            the core library built in the fork (``uv run build_lib.py``)
    _generated.py   fork commit, required warp-lang version, overlaid module names

None of this is committed; ``tools/release.py`` runs the generator and builds the wheel.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "src", "warp_metal")
GENERATED = ["_overlay", "native", "bin", "_generated.py"]

# Native subdirectories needed to compile CPU and Metal kernels (CUDA-only material is left out).
NATIVE_SUBDIRS = ["nanovdb", "clang"]

# Python files that differ from stock but must not, or need not, be overlaid.
NOT_OVERLAID = {
    "__init__.py": "only adds the is_metal_available export, which the import hook provides",
    "__init__.pyi": "type stub, not used at run time",
    "config.py": "differs only in the recorded git commit hash",
    "_src/build_dll.py": "only used to build the native library",
}


def run(cmd, cwd):
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def read_normalized(path):
    """File contents with LF line endings (the stock macOS wheel is packed with CRLF)."""
    with open(path, "rb") as f:
        return f.read().replace(b"\r\n", b"\n")


def stock_metadata(stock):
    """Return (version, source commit) of an unpacked stock warp-lang wheel."""
    config = read_normalized(os.path.join(stock, "warp", "config.py")).decode()
    version = re.search(r'^version: str = "([^"]+)"', config, re.M)
    commit = re.search(r'^_git_commit_hash: str \| None = "([0-9a-f]{40})"', config, re.M)
    if not version:
        sys.exit("error: could not read the version from the stock warp/config.py")
    return version.group(1), commit.group(1) if commit else None


def differing_python_files(fork, stock):
    """Python files of the ``warp`` package (tests and examples aside) that differ from stock."""
    fork_pkg, stock_pkg = os.path.join(fork, "warp"), os.path.join(stock, "warp")
    differing = []
    for base, dirs, files in os.walk(fork_pkg):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "bin", "native", "tests", "examples")]
        for name in files:
            if not name.endswith((".py", ".pyi")):
                continue
            rel = os.path.relpath(os.path.join(base, name), fork_pkg)
            stock_file = os.path.join(stock_pkg, rel)
            if not os.path.exists(stock_file) or read_normalized(os.path.join(base, name)) != read_normalized(
                stock_file
            ):
                differing.append(rel.replace(os.sep, "/"))
    return sorted(differing)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fork", help="checkout of https://github.com/DavidDobas/warp with warp/bin built")
    ap.add_argument("--stock", required=True, help="directory with the unpacked stock warp-lang wheel")
    ap.add_argument("--revision", default=None, help="two-digit revision appended to the Warp version")
    ap.add_argument("--allow-dirty", action="store_true", help="accept uncommitted changes in the fork")
    args = ap.parse_args()
    fork, stock = os.path.abspath(args.fork), os.path.abspath(args.stock)

    # 1. the fork and the stock wheel must belong together
    warp_version, stock_commit = stock_metadata(stock)
    fork_version = open(os.path.join(fork, "VERSION.md")).read().strip()
    if fork_version != warp_version:
        sys.exit(f"error: the fork is at version {fork_version}, the stock wheel is {warp_version}")
    if stock_commit is None:
        print("warning: the stock wheel records no source commit; cannot check the fork's base", file=sys.stderr)
    else:
        try:
            run(["git", "merge-base", "--is-ancestor", stock_commit, "HEAD"], fork)
        except subprocess.CalledProcessError:
            sys.exit(
                f"error: the stock wheel was built from upstream commit {stock_commit[:12]}, which the fork "
                "does not contain. Merge that commit into the fork first, otherwise the overlay would "
                "revert upstream changes."
            )
        ahead = run(["git", "rev-list", "--count", "--first-parent", f"{stock_commit}..HEAD"], fork)
        print(f"fork contains upstream {stock_commit[:12]} plus {ahead} first-parent commits")
    commit = run(["git", "rev-parse", "HEAD"], fork)
    if run(["git", "status", "--porcelain", "--untracked-files=no"], fork) and not args.allow_dirty:
        sys.exit("error: the fork checkout has uncommitted changes (pass --allow-dirty to accept them)")

    # 2. which modules to overlay
    modules = []
    for rel in differing_python_files(fork, stock):
        if rel in NOT_OVERLAID:
            print(f"not overlaid: warp/{rel} ({NOT_OVERLAID[rel]})")
        elif re.fullmatch(r"_src/\w+\.py", rel) and rel != "_src/__init__.py":
            modules.append(rel[len("_src/") : -len(".py")])
        else:
            sys.exit(
                f"error: warp/{rel} differs from stock but the import hook only overlays top-level modules of "
                "warp._src. Extend the hook, or list the file in NOT_OVERLAID with the reason."
            )
    if not modules:
        sys.exit("error: no module differs from stock; is --stock really the stock wheel?")

    # 3. write the generated tree
    for name in GENERATED:
        path = os.path.join(PKG, name)
        shutil.rmtree(path) if os.path.isdir(path) else os.path.exists(path) and os.remove(path)
    overlay = os.path.join(PKG, "_overlay")
    os.makedirs(overlay)
    for m in modules:
        shutil.copy2(os.path.join(fork, "warp", "_src", f"{m}.py"), overlay)
    open(os.path.join(overlay, "__init__.py"), "w").close()

    native_src, native_dst = os.path.join(fork, "warp", "native"), os.path.join(PKG, "native")
    os.makedirs(native_dst)
    for name in sorted(os.listdir(native_src)):
        path = os.path.join(native_src, name)
        if os.path.isfile(path) and (name.endswith((".h", ".exports")) or name == "crt.cpp"):
            shutil.copy2(path, native_dst)
    for sub in NATIVE_SUBDIRS:
        shutil.copytree(
            os.path.join(native_src, sub), os.path.join(native_dst, sub), ignore=shutil.ignore_patterns("*.o", "*.cu")
        )

    # the core library; the LLVM helper library comes from the stock warp-lang package at run time
    library = os.path.join(fork, "warp", "bin", "libwarp.dylib")
    if not os.path.exists(library):
        sys.exit("error: warp/bin/libwarp.dylib is missing; run `uv run build_lib.py` in the fork")
    newest_source = max(
        os.path.getmtime(os.path.join(native_src, n)) for n in os.listdir(native_src) if n.endswith((".cpp", ".mm", ".h"))
    )
    if os.path.getmtime(library) < newest_source:
        sys.exit("error: warp/bin/libwarp.dylib is older than the native sources; rebuild it in the fork")
    os.makedirs(os.path.join(PKG, "bin"))
    shutil.copy2(library, os.path.join(PKG, "bin"))

    with open(os.path.join(PKG, "_generated.py"), "w") as f:
        f.write('"""Written by tools/generate.py; not committed."""\n\n')
        f.write(f'FORK_COMMIT = "{commit}"\n')
        f.write(f'REQUIRED_WARP_VERSION = "{warp_version}"\n')
        f.write(f"OVERLAY_MODULES = {modules!r}\n")

    # 4. the package version and its pin follow the Warp version
    pyproject = os.path.join(ROOT, "pyproject.toml")
    text = open(pyproject).read()
    text = re.sub(r'"warp-lang==[^"]+"', f'"warp-lang=={warp_version}"', text)
    if args.revision is not None:
        if not re.fullmatch(r"\d\d", args.revision):
            sys.exit("error: --revision takes two digits, e.g. 01")
        text = re.sub(r'(?m)^version = "[^"]+"', f'version = "{package_version(warp_version, args.revision)}"', text)
    open(pyproject, "w").write(text)
    print(f"generated from fork commit {commit[:12]} for warp-lang {warp_version}: overlays {', '.join(modules)}")


def package_version(warp_version, revision):
    """``1.18.0`` -> ``1.18.0.NN``; nightlies ``1.18.0.devYYYYMMDD`` -> ``1.18.0.devYYYYMMDDNN``."""
    return warp_version + revision if ".dev" in warp_version else f"{warp_version}.{revision}"


if __name__ == "__main__":
    main()
