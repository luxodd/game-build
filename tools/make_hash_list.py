"""Write the published hash list for one Unity plugin release.

usage: make_hash_list.py <release.unitypackage> <version> <out.json>

The list covers every file the package installs (assets and their .meta files), keyed by
project-relative path, plus the sha256 of the package itself. It is the file the build
workflow checks a project against after installing the pinned plugin.
"""
import hashlib, json, sys, tarfile

def package_entries(pkg):
    entries = {}
    with tarfile.open(pkg, "r:gz") as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            parts = m.name.lstrip("./").split("/")
            if len(parts) == 2:
                entries.setdefault(parts[0], {})[parts[1]] = t.extractfile(m).read()
    files = {}
    for e in entries.values():
        if "pathname" not in e:
            continue
        rel = e["pathname"].decode("utf-8").splitlines()[0].strip()
        if ".." in rel.split("/") or rel.startswith("/"):
            raise SystemExit(f"refusing unsafe path in package: {rel!r}")
        if "asset" in e:
            files[rel] = hashlib.sha256(e["asset"]).hexdigest()
        if "asset.meta" in e:
            files[rel + ".meta"] = hashlib.sha256(e["asset.meta"]).hexdigest()
    return files

def main():
    pkg, version, out = sys.argv[1:4]
    data = open(pkg, "rb").read()
    manifest = {
        "plugin": "luxodd/unity-plugin",
        "version": version,
        "package_sha256": hashlib.sha256(data).hexdigest(),
        "roots": ["Assets/Luxodd.Game", "Assets/WebGLTemplates/LuxoddTemplate"],
        "files": dict(sorted(package_entries(pkg).items())),
    }
    with open(out, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=False)
        f.write("\n")
    print(f"{out}: {len(manifest['files'])} files, package {manifest['package_sha256'][:12]}")

if __name__ == "__main__":
    main()
