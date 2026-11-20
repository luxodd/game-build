"""Write the published hash list for one Unity plugin release.

usage: make_hash_list.py <release.unitypackage> <version> <out.json>
       make_hash_list.py --preview <git-dir> <commit-sha> <owner/repo> <path-prefix> <version> <out.json>

A release list covers every file the package installs (assets and their .meta files), keyed by
project-relative path, plus the sha256 of the package itself. It is the file the build
workflow checks a project against after installing the pinned plugin.

A preview list (channel "preview") has no package: it covers every file under the same roots
in the plugin's source repo at one full commit SHA, read with `git archive`, and records the
repo, commit and path prefix instead of a package hash. Release lists are never rewritten.
"""
import hashlib, io, json, re, subprocess, sys, tarfile

ROOTS = ["Assets/Luxodd.Game", "Assets/WebGLTemplates/LuxoddTemplate"]
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"

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

def tree_entries(git_dir, commit, prefix):
    """sha256 of every file under the roots (and the roots' own .meta) at one commit."""
    paths = [prefix + r for r in ROOTS] + [prefix + r + ".meta" for r in ROOTS]
    tar = subprocess.run(["git", "-C", git_dir, "archive", "--format=tar", commit, "--", *paths],
                         capture_output=True, check=True).stdout
    files = {}
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            data = t.extractfile(m).read()
            if data.startswith(LFS_POINTER):
                raise SystemExit(f"{m.name} is a Git LFS pointer; preview lists need real file content")
            files[m.name[len(prefix):]] = hashlib.sha256(data).hexdigest()
    return files

def main_preview(args):
    git_dir, commit, repo, prefix, version, out = args
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit("a preview list must be pinned to a full 40-character commit SHA")
    prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
    manifest = {
        "plugin": "luxodd/unity-plugin",
        "version": version,
        "channel": "preview",
        "source": {"repository": repo, "commit": commit, "path_prefix": prefix},
        "roots": ROOTS,
        "files": dict(sorted(tree_entries(git_dir, commit, prefix).items())),
    }
    with open(out, "w") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    print(f"{out}: {len(manifest['files'])} files, preview {repo}@{commit[:12]}")

def main():
    if sys.argv[1:2] == ["--preview"]:
        return main_preview(sys.argv[2:])
    pkg, version, out = sys.argv[1:4]
    data = open(pkg, "rb").read()
    manifest = {
        "plugin": "luxodd/unity-plugin",
        "version": version,
        "package_sha256": hashlib.sha256(data).hexdigest(),
        "roots": ROOTS,
        "files": dict(sorted(package_entries(pkg).items())),
    }
    with open(out, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=False)
        f.write("\n")
    print(f"{out}: {len(manifest['files'])} files, package {manifest['package_sha256'][:12]}")

if __name__ == "__main__":
    main()
