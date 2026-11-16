"""Replace a Unity project's Luxodd plugin with the pinned official release.

usage: install_plugin.py <project-dir> <release.unitypackage> <manifest.json>

Refuses a package whose sha256 is not the manifest's. Deletes the manifest's roots from the
project first, so no stale or added file survives, then writes every package file.
"""
import hashlib, json, os, shutil, sys, tarfile

def main():
    project, pkg, manifest_path = sys.argv[1:4]
    manifest = json.load(open(manifest_path))
    data = open(pkg, "rb").read()
    got = hashlib.sha256(data).hexdigest()
    if got != manifest["package_sha256"]:
        raise SystemExit(f"package sha256 {got} does not match manifest {manifest['package_sha256']}")
    for root in manifest["roots"]:
        target = os.path.join(project, root)
        if os.path.isdir(target):
            shutil.rmtree(target)
        if os.path.exists(target + ".meta") and root != "Assets/Luxodd.Game":
            pass  # folder .meta files are part of the package and get rewritten below
    entries = {}
    with tarfile.open(pkg, "r:gz") as t:
        for m in t.getmembers():
            parts = m.name.lstrip("./").split("/")
            if m.isfile() and len(parts) == 2:
                entries.setdefault(parts[0], {})[parts[1]] = t.extractfile(m).read()
    written = 0
    for e in entries.values():
        if "pathname" not in e:
            continue
        rel = e["pathname"].decode("utf-8").splitlines()[0].strip()
        if ".." in rel.split("/") or rel.startswith("/"):
            raise SystemExit(f"refusing unsafe path in package: {rel!r}")
        dst = os.path.join(project, rel)
        if "asset" in e:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(e["asset"]); written += 1
        else:
            os.makedirs(dst, exist_ok=True)
        if "asset.meta" in e:
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            open(dst + ".meta", "wb").write(e["asset.meta"])
    print(f"installed {manifest['plugin']} {manifest['version']}: {written} files")

if __name__ == "__main__":
    main()
