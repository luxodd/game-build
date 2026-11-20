"""Check a Unity project's plugin files against a published hash list.

usage: verify_plugin.py <project-dir> <manifest.json> [--report out.json]
                        [--allow-import-rewrites <baseline-dir>]

Fails (exit 1) on any changed, missing or added file under the manifest's roots. Byte-exact:
the workflow installs the plugin itself, so there is nothing to normalise. Release and preview
lists are checked the same way; a preview list must be pinned to a full commit SHA.

--allow-import-rewrites (post-build re-verify only). Unity's importers re-serialize some .meta
files on import (seen: TextureImporter on 6000.6 filling internalIDToNameTable). With this flag a
changed .meta passes only if all of these hold, and it is listed under "import_rewrites":
  - it is the .meta of a non-code asset outside the WebGL template;
  - its importer is on IMPORT_REWRITE_IMPORTERS (TextureImporter, AudioImporter) in both versions;
  - its guid and importer type are unchanged.
<baseline-dir> holds the plugin files as installed (copied before the build); each baseline
file must itself match the hash list. Every other change still fails: any non-.meta file, the
meta of code assets (.cs, .dll, .jslib, .jspre, .asmdef, .asmref, .rsp, native libraries), any
PluginImporter meta, and anything under the template.
"""
import difflib, hashlib, json, os, re, sys

IMPORT_REWRITE_IMPORTERS = {"TextureImporter", "AudioImporter"}
CODE_ASSET_EXTS = {".cs", ".dll", ".jslib", ".jspre", ".asmdef", ".asmref", ".rsp", ".so", ".a",
                   ".bundle", ".dylib", ".framework", ".jar", ".aar", ".mm", ".m", ".c", ".cc",
                   ".cpp", ".h", ".java", ".js", ".wasm"}
TEMPLATE_ROOT = "Assets/WebGLTemplates/LuxoddTemplate"

def meta_fields(data):
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    guid = re.search(r"^guid:\s*([0-9a-fA-F]+)\s*$", text, re.M)
    importer = re.search(r"^([A-Za-z]+Importer):\s*$", text, re.M)
    return text, (guid.group(1) if guid else None), (importer.group(1) if importer else None)

def import_rewrite(rel, old, new):
    """None if this .meta change may pass, else the reason it may not; plus a summary."""
    if not rel.endswith(".meta"):
        return "not a .meta file", None
    asset = rel[:-5]
    if asset == TEMPLATE_ROOT or asset.startswith(TEMPLATE_ROOT + "/"):
        return "WebGL template file", None
    if os.path.splitext(asset)[1].lower() in CODE_ASSET_EXTS or "/Plugins/" in "/" + asset + "/":
        return "meta of a code or plugin asset", None
    old_text, old_guid, old_imp = meta_fields(old)
    new_text, new_guid, new_imp = meta_fields(new)
    if "PluginImporter" in (old_imp, new_imp):
        return "PluginImporter meta", None
    if old_imp != new_imp:
        return f"importer changed {old_imp} -> {new_imp}", None
    if old_imp not in IMPORT_REWRITE_IMPORTERS:
        return f"importer {old_imp} is not on the import-rewrite allowlist", None
    if not old_guid or old_guid != new_guid:
        return "guid changed", None
    diff = [l for l in difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), lineterm="", n=0)
            if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    keys = sorted({m.group(1) for l in diff for m in [re.match(r"[+-]\s*-?\s*([A-Za-z_]\w*):", l)] if m})
    summary = {"importer": old_imp, "lines_added": sum(l[0] == "+" for l in diff),
               "lines_removed": sum(l[0] == "-" for l in diff),
               "line_endings_changed": ("\r\n" in old.decode("utf-8", "replace")) != ("\r\n" in new.decode("utf-8", "replace")),
               "keys": keys[:40]}
    return None, summary

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
    report_path, baseline = None, None
    if "--report" in args:
        i = args.index("--report"); report_path = args[i + 1]; del args[i:i + 2]
    if "--allow-import-rewrites" in args:
        i = args.index("--allow-import-rewrites"); baseline = args[i + 1]; del args[i:i + 2]
    project, manifest_path = args
    manifest = json.load(open(manifest_path))
    channel = manifest.get("channel", "release")
    if channel == "preview" and not re.fullmatch(r"[0-9a-f]{40}", str((manifest.get("source") or {}).get("commit", ""))):
        raise SystemExit("preview list must be pinned to a full 40-character commit SHA")
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
    rewrites, refused = [], []
    if baseline and changed:
        for rel in list(changed):
            bp = os.path.join(baseline, rel)
            if not os.path.isfile(bp):
                refused.append({"path": rel, "reason": "no baseline copy"}); continue
            old = open(bp, "rb").read()
            if hashlib.sha256(old).hexdigest() != expected[rel]:
                refused.append({"path": rel, "reason": "baseline copy does not match the hash list"}); continue
            new = open(found.get(rel) or os.path.join(project, rel), "rb").read()
            reason, summary = import_rewrite(rel, old, new)
            if reason:
                refused.append({"path": rel, "reason": reason}); continue
            rewrites.append({"path": rel, "old_sha256": expected[rel],
                             "new_sha256": hashlib.sha256(new).hexdigest(), **summary})
            changed.remove(rel)
    result = {"plugin": manifest["plugin"], "version": manifest["version"], "channel": channel,
              "source_commit": (manifest.get("source") or {}).get("commit"),
              "checked": len(expected), "changed": changed, "missing": missing, "added": added,
              "import_rewrites": rewrites, "refused_rewrites": refused,
              "ok": not (changed or missing or added)}
    if report_path:
        json.dump(result, open(report_path, "w"), indent=1)
    print(f"{manifest['plugin']} {manifest['version']}" + (" (preview)" if channel == "preview" else "") +
          f": {len(expected)} files, " + (f"{len(rewrites)} import rewrites accepted, " if baseline else "") +
          f"{len(changed)} changed, {len(missing)} missing, {len(added)} added")
    for k in ("changed", "missing", "added"):
        for rel in result[k]:
            print(f"  {k}: {rel}")
    for x in refused:
        print(f"  not an import rewrite: {x['path']} ({x['reason']})")
    for x in rewrites:
        print(f"  import rewrite: {x['path']} ({x['importer']}, +{x['lines_added']}/-{x['lines_removed']} lines)")
    sys.exit(0 if result["ok"] else 1)

if __name__ == "__main__":
    main()
