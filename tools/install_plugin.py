"""Replace a Unity project's Luxodd plugin with the pinned official release.

usage: install_plugin.py <project-dir> <release.unitypackage | preview-source> <manifest.json>

Release list: refuses a package whose sha256 is not the manifest's. Deletes the manifest's roots
from the project first, so no stale or added file survives, then writes every package file.

Preview list (channel "preview"): the source is the plugin repo at the list's commit, as a
GitHub tarball, a `git archive` tar, or a directory. Every file under the roots must be in the
list with the same sha256, and every listed file must be present, before anything is written.
"""
import hashlib, json, os, re, shutil, sys, tarfile

def load_manifest(path):
    m = json.load(open(path))
    if m.get("channel", "release") == "preview":
        src = m.get("source") or {}
        if not re.fullmatch(r"[0-9a-f]{40}", str(src.get("commit", ""))) or not src.get("repository"):
            raise SystemExit("preview list must name its source repository and a full 40-character commit SHA")
        if "package_sha256" in m:
            raise SystemExit("preview list must not carry a package sha256")
    elif not re.fullmatch(r"[0-9a-f]{64}", str(m.get("package_sha256", ""))):
        raise SystemExit("release list has no package sha256")
    return m

def preview_files(source, manifest):
    """{project-relative path: bytes} for every file under the roots in the preview source."""
    prefix = manifest["source"].get("path_prefix", "")
    roots = manifest["roots"]
    wanted = lambda rel: any(rel == r + ".meta" or rel.startswith(r + "/") for r in roots)
    out = {}
    def take(name, read):
        name = name.lstrip("./")
        # GitHub tarballs put everything under one "<owner>-<repo>-<sha>/" folder.
        anchor = prefix + "Assets/"
        if not name.startswith(anchor) and "/" in name and name.split("/", 1)[1].startswith(anchor):
            name = name.split("/", 1)[1]
        if not name.startswith(prefix):
            return
        rel = name[len(prefix):]
        if ".." in rel.split("/") or rel.startswith("/"):
            raise SystemExit(f"refusing unsafe path in preview source: {rel!r}")
        if wanted(rel):
            out[rel] = read()
    if os.path.isdir(source):
        for d, _, fs in os.walk(source):
            for f in fs:
                p = os.path.join(d, f)
                take(os.path.relpath(p, source).replace(os.sep, "/"), lambda p=p: open(p, "rb").read())
    else:
        with tarfile.open(source) as t:
            for m in t.getmembers():
                if m.isfile():
                    take(m.name, lambda m=m: t.extractfile(m).read())
    return out

def install_preview(project, source, manifest):
    files = preview_files(source, manifest)
    expected = manifest["files"]
    bad = [r for r, b in files.items() if hashlib.sha256(b).hexdigest() != expected.get(r)]
    missing = sorted(set(expected) - set(files))
    if bad or missing:
        raise SystemExit(f"preview source does not match the list at {manifest['source']['commit'][:12]}: "
                         f"{len(bad)} changed or unlisted, {len(missing)} missing (e.g. {(bad + missing)[:3]})")
    for root in manifest["roots"]:
        target = os.path.join(project, root)
        if os.path.isdir(target):
            shutil.rmtree(target)
    for rel, data in files.items():
        dst = os.path.join(project, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(data)
    print(f"installed {manifest['plugin']} {manifest['version']} (preview "
          f"{manifest['source']['repository']}@{manifest['source']['commit'][:12]}): {len(files)} files")

def main():
    project, pkg, manifest_path = sys.argv[1:4]
    manifest = load_manifest(manifest_path)
    if manifest.get("channel") == "preview":
        return install_preview(project, pkg, manifest)
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
