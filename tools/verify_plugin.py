"""Check a Unity project's plugin files against a published hash list.

usage: verify_plugin.py <project-dir> <manifest.json> [--report out.json]

Fails (exit 1) on any changed, missing or added file under the manifest's roots. Byte-exact:
the workflow installs the plugin itself, so there is nothing to normalise.
"""
import hashlib, json, os, sys

def scan(project, roots):
    found = {}
    for root in roots:
        base = os.path.join(project, root)
        for d, _, fs in os.walk(base):
            for f in fs:
                if f == ".DS_Store":
                    continue
                p = os.path.join(d, f)
                found[os.path.relpath(p, project).replace(os.sep, "/")] = p
    return found

def main():
    args = sys.argv[1:]
    report_path = None
    if "--report" in args:
        i = args.index("--report"); report_path = args[i + 1]; del args[i:i + 2]
    project, manifest_path = args
    manifest = json.load(open(manifest_path))
    expected = manifest["files"]
    found = scan(project, manifest["roots"])
    changed, missing = [], []
    for rel, digest in expected.items():
        p = found.get(rel)
        if p is None:
            # files outside the roots (a root folder's own .meta; older releases also
            # install Assets/Fonts and Assets/TextMesh Pro) are checked by exact path
            if os.path.isfile(os.path.join(project, rel)):
                p = os.path.join(project, rel)
            else:
                missing.append(rel); continue
        if hashlib.sha256(open(p, "rb").read()).hexdigest() != digest:
            changed.append(rel)
    added = sorted(set(found) - set(expected))
    result = {"plugin": manifest["plugin"], "version": manifest["version"],
              "checked": len(expected), "changed": changed, "missing": missing, "added": added,
              "ok": not (changed or missing or added)}
    if report_path:
        json.dump(result, open(report_path, "w"), indent=1)
    print(f"{manifest['plugin']} {manifest['version']}: {len(expected)} files, "
          f"{len(changed)} changed, {len(missing)} missing, {len(added)} added")
    for k in ("changed", "missing", "added"):
        for rel in result[k]:
            print(f"  {k}: {rel}")
    sys.exit(0 if result["ok"] else 1)

if __name__ == "__main__":
    main()
