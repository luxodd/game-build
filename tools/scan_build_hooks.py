"""Find editor build hooks outside the Luxodd plugin that could touch plugin code.

usage: scan_build_hooks.py <project-dir> [--report out.json] [--allow <path>]...

Scans C# under Assets/ and embedded packages under Packages/ (not Assets/Luxodd.Game, not the
workflow's own Assets/LuxoddBuild). Two levels:
  fail   - a build-pipeline callback (interface or [PostProcessBuild]/[PostProcessScene]) in a
           file that names the plugin (Luxodd.Game, its assemblies, LuxoddTemplate) and either
           is an assembly-level hook (script DLLs, assembly filter, linker), rewrites IL, or
           writes to a path built from a plugin name (a literal, or a variable assigned from
           one, followed through assignments);
  review - any other build callback (including one that names the plugin but only reads or
           checks it), [DidReloadScripts], or editor code that names the plugin and writes
           files. Listed for the reviewer; does not fail the build.
The write check follows assignments within one file only. Indirection it cannot see (helpers in
other files, reflection, string building it cannot follow) is why review still matters.
Also lists precompiled editor DLLs it cannot read. This catches the obvious
cases only (attestation design, "Build hooks"); review still matters.
"""
import json, os, re, sys

HOOK_INTERFACES = [
    "IPreprocessBuildWithReport", "IPostprocessBuildWithReport", "IPreprocessBuild",
    "IPostprocessBuild", "IPostBuildPlayerScriptDLLs", "IFilterBuildAssemblies",
    "IProcessSceneWithReport", "IProcessScene", "IPreprocessShaders", "IPreprocessComputeShaders",
    "IUnityLinkerProcessor", "IPostGenerateGradleAndroidProject",
]
HOOK_ATTRIBUTES = ["PostProcessBuild", "PostProcessScene", "DidReloadScripts"]
PLUGIN_NAMES = re.compile(r"Luxodd\.Game|LuxoddTemplate|Luxodd\.Game\.Runtime|Luxodd\.Game\.Editor")
FILE_WRITES = re.compile(r"File\.(Write|Copy|Move|Delete|Replace|AppendAll)|FileStream|AssetDatabase\.(DeleteAsset|MoveAsset|CopyAsset)|CompilationPipeline")
# Hooks that act on compiled assemblies: naming the plugin is enough to fail.
ASSEMBLY_HOOKS = {"IPostBuildPlayerScriptDLLs", "IFilterBuildAssemblies", "IUnityLinkerProcessor"}
IL_REWRITE = re.compile(r"\bMono\.Cecil\b|\bdnlib\b|\bHarmonyLib\b|AssemblyDefinition\.ReadAssembly")
WRITE_OPS = re.compile(
    r"\bFile\.(Write\w*|Copy|Move|Delete|Replace|AppendAll\w*|Create\w*|Open(Write)?|SetAttributes)\s*\("
    r"|\bnew\s+(FileStream|StreamWriter|BinaryWriter|FileInfo)\s*\("
    r"|\bDirectory\.(Delete|Move|CreateDirectory)\s*\("
    r"|\bFileUtil\.\w+\s*\("
    r"|\bAssetDatabase\.(DeleteAsset|MoveAsset|CopyAsset|CreateAsset|RenameAsset|ImportAsset|MoveAssetToTrash)\s*\("
    r"|\.(CopyTo|MoveTo|Delete)\s*\(")
ASSIGN = re.compile(r"\b(\w+)\s*=(?![=>])([^;{}]*)")

def plugin_targeted_writes(src):
    """Statements that write to something derived from a plugin name, following assignments."""
    tainted, statements = set(), [x for x in re.split(r"[;{}]", src) if x.strip()]
    def is_tainted(text):
        return bool(PLUGIN_NAMES.search(text)) or any(re.search(r"\b" + re.escape(t) + r"\b", text) for t in tainted)
    changed = True
    while changed:
        changed = False
        for st in statements:
            for name, rhs in ASSIGN.findall(st):
                if name not in tainted and is_tainted(rhs):
                    tainted.add(name); changed = True
    return [" ".join(st.split())[:160] for st in statements if WRITE_OPS.search(st) and is_tainted(st)]
SKIP_PREFIXES = ("Assets/Luxodd.Game/", "Assets/LuxoddBuild/")

def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)

def main():
    args = sys.argv[1:]
    report_path, allow = None, []
    while "--report" in args:
        i = args.index("--report"); report_path = args[i + 1]; del args[i:i + 2]
    while "--allow" in args:
        i = args.index("--allow"); allow.append(args[i + 1]); del args[i:i + 2]
    project = args[0]
    findings, unreadable = [], []
    for top in ("Assets", "Packages"):
        for d, dirs, fs in os.walk(os.path.join(project, top)):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for f in fs:
                p = os.path.join(d, f)
                rel = os.path.relpath(p, project).replace(os.sep, "/")
                if rel.startswith(SKIP_PREFIXES) or rel in allow:
                    continue
                if f.endswith(".dll") and "/Editor/" in "/" + rel:
                    unreadable.append(rel); continue
                if not f.endswith(".cs"):
                    continue
                src = strip_comments(open(p, encoding="utf-8", errors="replace").read())
                hits = [i for i in HOOK_INTERFACES if re.search(r"[:,]\s*(\w+\.)*" + i + r"\b", src)]
                hits += ["[" + a + "]" for a in HOOK_ATTRIBUTES if re.search(r"\[\s*(\w+\.)*" + a + r"\b", src)]
                names_plugin = bool(PLUGIN_NAMES.search(src))
                build_hooks = [h for h in hits if h != "[DidReloadScripts]"]
                writes_plugin = names_plugin and bool(FILE_WRITES.search(src))
                targeted = plugin_targeted_writes(src) if names_plugin else []
                if build_hooks and names_plugin and (
                        ASSEMBLY_HOOKS.intersection(build_hooks) or IL_REWRITE.search(src) or targeted):
                    level = "fail"
                elif hits or writes_plugin:
                    level = "review"
                else:
                    continue
                findings.append({"file": rel, "level": level, "hooks": hits,
                                 "names_plugin": names_plugin, "writes_files_naming_plugin": writes_plugin,
                                 "plugin_targeted_writes": targeted})
    fails = [x for x in findings if x["level"] == "fail"]
    result = {"project": project, "findings": findings, "unreadable_editor_dlls": unreadable,
              "ok": not fails}
    if report_path:
        json.dump(result, open(report_path, "w"), indent=1)
    for x in findings:
        what = ", ".join(x["hooks"]) or "-"
        print(f"  {x['level']}: {x['file']}  [{what}]" + ("  names plugin" if x["names_plugin"] else ""))
        for st in x["plugin_targeted_writes"][:3]:
            print(f"      writes: {st}")
    for x in unreadable:
        print(f"  note: precompiled editor DLL not scanned: {x}")
    print(f"{len(fails)} fail, {len(findings) - len(fails)} review, {len(unreadable)} unscanned editor DLL(s)")
    sys.exit(0 if result["ok"] else 1)

if __name__ == "__main__":
    main()
