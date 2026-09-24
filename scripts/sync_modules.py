"""Keep the vendored modules in step with their owners' repositories.

Each module under services/ is a copy of its upstream repo at the commit in
modules.lock.json, plus the integration changes in patches/<name>.patch.

    python scripts/sync_modules.py status              which files differ from upstream
    python scripts/sync_modules.py patch [name ...]    regenerate patches/<name>.patch from services/<name>
    python scripts/sync_modules.py pull NAME [--ref R] re-vendor NAME from upstream at R, re-apply its patch

Data directories (data/, cache/, outputs/) are never touched.
"""

from __future__ import annotations

import argparse
import difflib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "modules.lock.json"
PATCHES = ROOT / "patches"
KEEP = {"data", "cache", "outputs", "node_modules", "__pycache__", ".pytest_cache"}


def load_lock() -> dict:
    return {k: v for k, v in json.loads(LOCK.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def git(*args: str, cwd: Path | None = None) -> bytes:
    # autocrlf off: compare against the bytes the owners committed, not a
    # Windows checkout of them.
    return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd, check=True, capture_output=True).stdout


def upstream_tree(entry: dict, ref: str, workdir: Path) -> tuple[dict[str, bytes], str]:
    """Files of the upstream repo at ref, as {relative path: bytes}, and the resolved commit."""
    clone = workdir / "clone"
    git("clone", "--quiet", "--filter=blob:none", "--no-checkout", entry["repo"], str(clone))
    commit = git("rev-parse", ref if len(ref) == 40 else f"origin/{ref}", cwd=clone).decode().strip()
    archive = git("archive", "--format=tar", commit, cwd=clone)
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if not member.isfile() or any(member.name.startswith(x) for x in entry.get("exclude", [])):
                continue
            if set(Path(member.name).parts) & KEEP:
                continue
            files[member.name] = _lf(tar.extractfile(member).read())
    return files, commit


def _lf(data: bytes) -> bytes:
    """This repo stores text with LF (.gitattributes); owners' repos mix CRLF and LF.
    Normalising upstream the same way keeps patches to real content changes."""
    return data if b"\0" in data[:8192] else data.replace(b"\r\n", b"\n")


def local_tree(name: str) -> dict[str, bytes]:
    base = ROOT / "services" / name
    out = {}
    for path in base.rglob("*"):
        rel = path.relative_to(base)
        if path.is_file() and not (set(rel.parts) & KEEP):
            out[rel.as_posix()] = path.read_bytes()
    return out


def _text(data: bytes) -> list[str] | None:
    try:
        return data.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None


def make_patch(name: str, upstream: dict[str, bytes]) -> str:
    local = local_tree(name)
    chunks = []
    for rel in sorted(set(upstream) & set(local)):
        if upstream[rel] == local[rel]:
            continue
        old, new = _text(upstream[rel]), _text(local[rel])
        if old is None or new is None:
            print(f"  skipping binary change: {rel}", file=sys.stderr)
            continue
        chunks.extend(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}"))
    return "".join(chunks)


def cmd_status(lock: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for name, entry in lock.items():
            upstream, _ = upstream_tree(entry, entry["commit"], Path(tmp) / name)
            local = local_tree(name)
            changed = sorted(r for r in set(upstream) & set(local) if upstream[r] != local[r])
            missing = sorted(set(upstream) - set(local))
            added = sorted(set(local) - set(upstream))
            print(f"{name}: {len(changed)} patched, {len(missing)} removed, {len(added)} local-only")
            for rel in changed:
                print(f"    M {rel}")


def cmd_patch(lock: dict, names: list[str]) -> None:
    PATCHES.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name in names or list(lock):
            upstream, _ = upstream_tree(lock[name], lock[name]["commit"], Path(tmp) / name)
            patch = make_patch(name, upstream)
            target = PATCHES / f"{name}.patch"
            if patch:
                target.write_text(patch, encoding="utf-8", newline="\n")
                print(f"wrote {target.relative_to(ROOT)} ({patch.count(chr(10))} lines)")
            else:
                target.unlink(missing_ok=True)
                print(f"{name}: identical to upstream, no patch")


def cmd_pull(lock: dict, name: str, ref: str | None) -> None:
    entry = lock[name]
    target = ROOT / "services" / name
    with tempfile.TemporaryDirectory() as tmp:
        upstream, commit = upstream_tree(entry, ref or entry["ref"], Path(tmp) / name)
        for path in list(target.iterdir()) if target.exists() else []:
            if path.name in KEEP:
                continue
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        for rel, data in upstream.items():
            out = target / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
    patch = PATCHES / f"{name}.patch"
    if patch.exists():
        result = subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", f"--directory=services/{name}", str(patch)], cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Patch did not apply cleanly - upstream changed the same lines:\n{result.stderr}")
            print("Resolve by hand, then run: python scripts/sync_modules.py patch", name)
            sys.exit(1)
    full = json.loads(LOCK.read_text(encoding="utf-8"))
    full[name]["commit"] = commit
    LOCK.write_text(json.dumps(full, indent=2) + "\n", encoding="utf-8")
    print(f"{name} now at {commit[:10]}" + (" with integration patch applied" if patch.exists() else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("patch")
    p.add_argument("names", nargs="*")
    p = sub.add_parser("pull")
    p.add_argument("name")
    p.add_argument("--ref")
    args = parser.parse_args()
    lock = load_lock()
    if args.cmd == "status":
        cmd_status(lock)
    elif args.cmd == "patch":
        cmd_patch(lock, args.names)
    else:
        cmd_pull(lock, args.name, args.ref)


if __name__ == "__main__":
    main()
