"""Versioned common core/UI source bundle; platform adapters and workspaces stay separate.

No network, installer or clinical input. Assembly always creates a new staging
directory and rejects unmerged changes against an explicit immutable base.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "shared-source-build.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def safe_name(name: str) -> str:
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or "\\" in name or str(p) != name:
        raise ValueError(f"Unsafe source path: {name}")
    return name


def source_bytes(root: Path, name: str) -> bytes:
    path = root / safe_name(name)
    if any(p.is_symlink() for p in [path, *path.parents[:len(PurePosixPath(name).parts)-1]]):
        raise ValueError(f"Source symlinks are not permitted: {name}")
    data = path.read_bytes()
    if len(data) > 4_000_000:
        raise ValueError(f"Unexpected source size: {name}")
    return data


def fingerprint(files: dict, component: str | None = None) -> str:
    subset = {p: row for p, row in files.items() if component is None or row["component"] == component}
    return sha(json.dumps(subset, sort_keys=True, separators=(",", ":")).encode())


def snapshot(root: Path = ROOT) -> tuple[dict, dict[str, bytes]]:
    root = root.resolve()
    policy = json.loads(source_bytes(root, "shared-source.json"))
    if policy["schema"] != 1:
        raise ValueError("Unsupported shared source policy")
    paths = {p.relative_to(root).as_posix(): "core" for p in (root / "ecg_core").glob("*.py")
             if p.name not in policy["native_adapter_modules"]}
    for pattern in policy["ui_globs"]:
        paths.update({p.relative_to(root).as_posix(): "ui" for p in root.glob(pattern) if p.is_file()})
    paths.update({p: "build" for p in policy["build_files"]})
    payload = {p: source_bytes(root, p) for p in sorted(paths)}
    files = {p: {"component": paths[p], "bytes": len(data), "sha256": sha(data)} for p, data in payload.items()}
    manifest = {"schema": 1, "core_contract": policy["core_contract"], "files": files,
                "core_version": "core-" + fingerprint(files, "core")[:16],
                "ui_version": "ui-" + fingerprint(files, "ui")[:16],
                "source_fingerprint": fingerprint(files), "capabilities": policy["capabilities"],
                "source_revision": None, "clinical_acceptance": False}
    return manifest, payload


def build(output: Path, root: Path = ROOT) -> dict:
    manifest, payload = snapshot(root)
    output = output.resolve()
    if output.exists():
        raise ValueError("Output already exists; preserve prior artifacts")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted({**payload, MANIFEST: encoded(manifest)}.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    read_bundle(output)
    return manifest


def read_bundle(bundle: Path) -> tuple[dict, dict[str, bytes]]:
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate bundle entries")
        for item in archive.infolist():
            safe_name(item.filename)
            if item.file_size > 4_000_000 or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Invalid bundle entry")
        manifest = json.loads(archive.read(MANIFEST))
        if manifest.get("schema") != 1 or set(names) != set(manifest["files"]) | {MANIFEST}:
            raise ValueError("Bundle manifest/file set mismatch")
        payload = {name: archive.read(name) for name in manifest["files"]}
    policy = json.loads(payload["shared-source.json"])
    for name, data in payload.items():
        row = manifest["files"][name]
        p = PurePosixPath(name)
        allowed = (p.parent == PurePosixPath("ecg_core") and p.suffix == ".py" and p.name not in policy["native_adapter_modules"])
        allowed = allowed or name in policy["build_files"] or any(p.match(g) for g in policy["ui_globs"])
        if not allowed or row["bytes"] != len(data) or row["sha256"] != sha(data):
            raise ValueError(f"Unapproved or modified common source: {name}")
    if fingerprint(manifest["files"]) != manifest["source_fingerprint"]:
        raise ValueError("Bundle fingerprint mismatch")
    for component, key in [("core", "core_version"), ("ui", "ui_version")]:
        if manifest[key] != component + "-" + fingerprint(manifest["files"], component)[:16]:
            raise ValueError("Component version mismatch")
    return manifest, payload


def check(bundle: Path, target: Path) -> dict:
    manifest, payload = read_bundle(bundle)
    changed, missing = [], []
    for name, data in payload.items():
        if not (target / name).is_file():
            missing.append(name)
        elif source_bytes(target, name) != data:
            changed.append(name)
    return {"matches": not changed and not missing, "changed": changed, "missing": missing,
            "core_version": manifest["core_version"], "ui_version": manifest["ui_version"]}


def stage(bundle: Path, adapter_root: Path, output: Path, profile: str, base: Path | None = None) -> dict:
    manifest, payload = read_bundle(bundle)
    policy = json.loads(payload["shared-source.json"])
    if profile not in policy["adapters"]:
        raise ValueError("Unknown platform adapter profile")
    if output.exists():
        raise ValueError("Staging output must be new; existing trees are never overwritten")
    expected = json.loads(base.read_text())["files"] if base else {}
    conflicts = []
    candidates = {p.relative_to(adapter_root).as_posix() for p in (adapter_root / "ecg_core").glob("*.py")
                  if p.name not in policy["native_adapter_modules"]}
    for pattern in policy["ui_globs"]:
        candidates.update(p.relative_to(adapter_root).as_posix() for p in adapter_root.glob(pattern) if p.is_file())
    conflicts.extend(sorted(candidates - set(payload)))
    for name, data in payload.items():
        if (adapter_root / name).exists():
            actual = source_bytes(adapter_root, name)
            if actual != data and expected.get(name) != git_blob(actual):
                conflicts.append(name)
    if conflicts:
        raise ValueError("Unmerged existing source changes: " + ", ".join(conflicts))
    adapters = {name: source_bytes(adapter_root, name) for name in policy["adapters"][profile]}
    if set(adapters) & set(payload):
        raise ValueError("Adapter/common-source ownership overlap")
    input_hashes = {p: sha(data) for p, data in adapters.items()}
    config_name = "ecg_core/config.py"
    config = adapters[config_name].decode()
    parsed = ast.parse(config)
    constants = {node.targets[0].id: node.value.value for node in parsed.body
                 if isinstance(node, ast.Assign) and len(node.targets) == 1
                 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)}
    if any(name in constants and constants[name] != value for name, value in {"SAMPLE_RATE": 200, "CHANNEL_COUNT": 8}.items()):
        raise ValueError("Platform adapter changes the shared sample/channel contract")
    if "from .core_contract import" not in config:
        for old in ("SAMPLE_RATE = 200\n", "CHANNEL_COUNT = 8\n"):
            if config.count(old) != 1:
                raise ValueError("Unrecognized platform sample/channel declarations")
            config = config.replace(old, "")
        config = config.replace("from pathlib import Path\n", "from pathlib import Path\nfrom .core_contract import SAMPLE_RATE, CHANNEL_COUNT\n", 1)
        adapters[config_name] = config.encode()
    if profile == "windows-doctor":
        builder_name = "scripts/windows_doctor_build.py"
        builder = adapters[builder_name].decode()
        if "'shared-source-build.json'," not in builder:
            if builder.count("ASSET_FILES = (\n") != 1:
                raise ValueError("Doctor build asset declaration changed; review adapter before assembly")
            builder = builder.replace("ASSET_FILES = (\n", "ASSET_FILES = (\n    'shared-source-build.json',\n", 1)
            adapters[builder_name] = builder.encode()
    receipt = {"schema": 1, "profile": profile, "core_version": manifest["core_version"],
               "ui_version": manifest["ui_version"], "source_fingerprint": manifest["source_fingerprint"],
               "adapter_input_files": input_hashes,
               "adapter_files": {p: sha(data) for p, data in adapters.items()},
               "input_tree_modified": False, "clinical_inputs_copied": False}
    output.mkdir(parents=True)
    for name, data in {**payload, **adapters, MANIFEST: encoded(manifest), "platform-source-build.json": encoded(receipt)}.items():
        p = output / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    assert check(bundle, output)["matches"]
    return receipt


def stamp(bundle: Path, target: Path) -> dict:
    """Write build metadata only after all common source bytes match."""
    if not check(bundle, target)["matches"]:
        raise ValueError("Source differs from shared package; cannot stamp build")
    manifest = read_bundle(bundle)[0]
    destination = target / MANIFEST
    if destination.exists() and destination.read_bytes() != encoded(manifest):
        raise ValueError("Existing build stamp differs; preserve and review it")
    destination.write_bytes(encoded(manifest))
    return {"core_version": manifest["core_version"], "ui_version": manifest["ui_version"], "source_fingerprint": manifest["source_fingerprint"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build"); b.add_argument("--output", type=Path, required=True)
    v = sub.add_parser("verify"); v.add_argument("bundle", type=Path)
    c = sub.add_parser("check"); c.add_argument("bundle", type=Path); c.add_argument("--target", type=Path, required=True)
    t = sub.add_parser("stamp"); t.add_argument("bundle", type=Path); t.add_argument("--target", type=Path, required=True)
    s = sub.add_parser("stage"); s.add_argument("bundle", type=Path); s.add_argument("--adapter-root", type=Path, required=True); s.add_argument("--output", type=Path, required=True); s.add_argument("--profile", required=True); s.add_argument("--base", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        result = build(args.output)
    elif args.command == "verify":
        result = read_bundle(args.bundle)[0]
    elif args.command == "check":
        result = check(args.bundle, args.target)
    elif args.command == "stamp":
        result = stamp(args.bundle, args.target)
    else:
        result = stage(args.bundle, args.adapter_root, args.output, args.profile, args.base)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "check" and not result["matches"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
