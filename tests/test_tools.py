"""Unit tests for the plugin install, hash check and build-hook scan.

Run: python -m pytest pipeline/game-build/tests -q
Uses a tiny synthetic .unitypackage, so it needs no Unity and no network.
"""
import hashlib, io, json, os, re, subprocess, sys, tarfile
import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")

def run(tool, *args):
    return subprocess.run([sys.executable, "-I", os.path.join(TOOLS, tool), *map(str, args)],
                          capture_output=True, text=True)

def make_package(path, files):
    with tarfile.open(path, "w:gz") as t:
        for i, (rel, data) in enumerate(files.items()):
            guid = f"{i:032x}"
            for name, content in (("pathname", rel.encode()), ("asset", data), ("asset.meta", b"guid: " + guid.encode())):
                info = tarfile.TarInfo(f"{guid}/{name}"); info.size = len(content)
                t.addfile(info, io.BytesIO(content))

@pytest.fixture
def release(tmp_path):
    pkg = tmp_path / "plugin.unitypackage"
    make_package(pkg, {
        "Assets/Luxodd.Game/Runtime/Core/Network/WebSocketService.cs": b"class WebSocketService {}\n",
        "Assets/Luxodd.Game/Plugins/WebGL/websocket.jslib": b"mergeInto(LibraryManager.library, {});\n",
        "Assets/WebGLTemplates/LuxoddTemplate/index.html": b"<html></html>\n",
    })
    manifest = tmp_path / "1.2.0.json"
    assert run("make_hash_list.py", pkg, "1.2.0", manifest).returncode == 0
    return pkg, manifest

@pytest.fixture
def project(tmp_path):
    p = tmp_path / "game"
    (p / "Assets/Luxodd.Game/Runtime/Core/Network").mkdir(parents=True)
    (p / "Assets/Luxodd.Game/Runtime/Core/Network/WebSocketService.cs").write_text("// edited by the game\n")
    (p / "Assets/Luxodd.Game/Stale.cs").write_text("// left over from an old plugin\n")
    (p / "Assets/Scripts").mkdir(parents=True)
    (p / "Assets/Scripts/Player.cs").write_text("class Player {}\n")
    return p

def test_install_replaces_edited_and_stale_files(release, project):
    pkg, manifest = release
    assert run("verify_plugin.py", project, manifest).returncode == 1
    assert run("install_plugin.py", project, pkg, manifest).returncode == 0
    r = run("verify_plugin.py", project, manifest)
    assert r.returncode == 0, r.stdout
    assert not (project / "Assets/Luxodd.Game/Stale.cs").exists()
    assert (project / "Assets/Scripts/Player.cs").exists()

def test_install_refuses_a_package_that_is_not_the_published_one(release, project, tmp_path):
    pkg, manifest = release
    other = tmp_path / "other.unitypackage"
    make_package(other, {"Assets/Luxodd.Game/Evil.cs": b"x"})
    r = run("install_plugin.py", project, other, manifest)
    assert r.returncode != 0 and "does not match" in (r.stdout + r.stderr)

@pytest.mark.parametrize("change", ["edit", "add", "remove"])
def test_verify_catches_each_kind_of_change(release, project, change):
    pkg, manifest = release
    run("install_plugin.py", project, pkg, manifest)
    target = project / "Assets/Luxodd.Game/Plugins/WebGL/websocket.jslib"
    if change == "edit":
        target.write_text("window.parent.postMessage({type:'session_end'}, '*');\n")
    elif change == "add":
        (project / "Assets/Luxodd.Game/Extra.cs").write_text("class Extra {}\n")
    else:
        target.unlink()
    assert run("verify_plugin.py", project, manifest).returncode == 1

def test_scan_fails_a_hook_that_names_the_plugin(project):
    ed = project / "Assets/Editor"; ed.mkdir()
    (ed / "Patch.cs").write_text(
        "using UnityEditor.Build;\nclass Patch : IPostBuildPlayerScriptDLLs {\n"
        "  void X() { System.IO.File.Copy(\"a\", \"Library/Bee/Luxodd.Game.Runtime.dll\"); } }\n")
    assert run("scan_build_hooks.py", project).returncode == 1

def test_scan_lists_but_passes_an_unrelated_hook(project):
    ed = project / "Assets/Editor"; ed.mkdir()
    (ed / "Stamp.cs").write_text("class Stamp : IPreprocessBuildWithReport { }\n")
    r = run("scan_build_hooks.py", project)
    assert r.returncode == 0 and "review: Assets/Editor/Stamp.cs" in r.stdout

def test_scan_ignores_commented_out_hooks(project):
    ed = project / "Assets/Editor"; ed.mkdir()
    (ed / "Old.cs").write_text("// class Old : IPostBuildPlayerScriptDLLs  Luxodd.Game\nclass Old {}\n")
    r = run("scan_build_hooks.py", project)
    assert r.returncode == 0 and "Old.cs" not in r.stdout

def test_scan_fails_a_hook_that_writes_into_the_plugin_through_a_variable(project):
    ed = project / "Assets/Editor"; ed.mkdir()
    (ed / "Swap.cs").write_text(
        "using System.IO; using UnityEditor.Build; using UnityEditor.Build.Reporting;\n"
        "class Swap : IPreprocessBuildWithReport {\n"
        "  const string Root = \"Assets/Luxodd.Game/Runtime\";\n"
        "  public int callbackOrder => 0;\n"
        "  public void OnPreprocessBuild(BuildReport r) {\n"
        "    var target = Path.Combine(Root, \"Core/PluginVersion.cs\");\n"
        "    File.WriteAllText(target, \"// patched\"); } }\n")
    r = run("scan_build_hooks.py", project)
    assert r.returncode == 1 and "fail: Assets/Editor/Swap.cs" in r.stdout and "File.WriteAllText" in r.stdout

def test_scan_fails_a_hook_that_deletes_the_template(project):
    ed = project / "Assets/Editor"; ed.mkdir()
    (ed / "Tpl.cs").write_text(
        "class Tpl : IPostprocessBuildWithReport { void OnPostprocessBuild(object r) {\n"
        "  System.IO.File.Delete(\"Assets/WebGLTemplates/LuxoddTemplate/index.html\"); } }\n")
    assert run("scan_build_hooks.py", project).returncode == 1

def test_scan_reviews_a_read_only_guard_that_skips_the_plugin_folder(project):
    # Shape of gravity-switch-game's WebGLReleaseGuard: names the plugin only to skip its
    # folder, and writes notices into the build output.
    ed = project / "Assets/Editor"; ed.mkdir()
    (ed / "ReleaseGuard.cs").write_text(
        "using System; using System.IO; using UnityEditor.Build; using UnityEditor.Build.Reporting;\n"
        "class ReleaseGuard : IPreprocessBuildWithReport, IPostprocessBuildWithReport {\n"
        "  const string PluginRoot = \"Assets/Luxodd.Game\";\n"
        "  public int callbackOrder => -10000;\n"
        "  public void OnPreprocessBuild(BuildReport r) {\n"
        "    foreach (var d in Directory.GetDirectories(\"Assets\", \"Resources\")) {\n"
        "      if (d.StartsWith(PluginRoot + \"/\", StringComparison.OrdinalIgnoreCase)) continue;\n"
        "      throw new BuildFailedException(d); } }\n"
        "  public void OnPostprocessBuild(BuildReport r) {\n"
        "    string notice = Path.Combine(r.summary.outputPath, \"ThirdPartyNotices/OFL.txt\");\n"
        "    Directory.CreateDirectory(Path.GetDirectoryName(notice));\n"
        "    File.Copy(\"Assets/Fonts/OFL.txt\", notice, true); } }\n")
    r = run("scan_build_hooks.py", project)
    assert r.returncode == 0 and "review: Assets/Editor/ReleaseGuard.cs" in r.stdout

def test_scan_reviews_a_guard_that_only_selects_the_template(project):
    # Shape of parabox-game's ParaboxLuxoddWebGLBuildGuard: checks the template exists and
    # sets the same WebGL settings the workflow forces.
    ed = project / "Assets/Editor"; ed.mkdir()
    (ed / "TemplateGuard.cs").write_text(
        "using System.IO; using UnityEditor; using UnityEditor.Build; using UnityEditor.Build.Reporting;\n"
        "class TemplateGuard : IPreprocessBuildWithReport {\n"
        "  const string TemplateName = \"PROJECT:LuxoddTemplate\";\n"
        "  const string TemplatePath = \"Assets/WebGLTemplates/LuxoddTemplate/index.html\";\n"
        "  public int callbackOrder => -1000;\n"
        "  public void OnPreprocessBuild(BuildReport r) {\n"
        "    if (!File.Exists(TemplatePath)) { string message = \"missing: \" + TemplatePath;\n"
        "      throw new BuildFailedException(message); }\n"
        "    PlayerSettings.WebGL.template = TemplateName;\n"
        "    PlayerSettings.WebGL.decompressionFallback = true;\n"
        "    AssetDatabase.SaveAssets(); } }\n")
    r = run("scan_build_hooks.py", project)
    assert r.returncode == 0 and "review: Assets/Editor/TemplateGuard.cs" in r.stdout

# ---- preview lists (plugin repo at a pinned commit, no package)

PREVIEW_TREE = {
    "Assets/Luxodd.Game.meta": b"folderAsset: yes\n",
    "Assets/Luxodd.Game/Runtime/Core/PluginVersion.cs": b'public const string Version = "1.3.0-preview.1";\n',
    "Assets/Luxodd.Game/Runtime/Core/PluginVersion.cs.meta": b"guid: 1\n",
    "Assets/Luxodd.Game/Runtime/Core/Network/TournamentInfoResult.cs": b"public enum TournamentInfoOutcome { Active }\n",
    "Assets/WebGLTemplates/LuxoddTemplate.meta": b"folderAsset: yes\n",
    "Assets/WebGLTemplates/LuxoddTemplate/index.html": b"<html>preview</html>\n",
}

def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, check=True).stdout.strip()

@pytest.fixture
def preview(tmp_path):
    repo = tmp_path / "unity-plugin-development"
    for rel, data in PREVIEW_TREE.items():
        p = repo / "UnityPluginDevelopment" / rel
        p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    (repo / "UnityPluginDevelopment/Assets/Other.cs").write_bytes(b"not plugin\n")
    git(tmp_path, "init", "-q", str(repo))
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "preview")
    sha = git(repo, "rev-parse", "HEAD")
    manifest = tmp_path / "1.3.0-preview.1.json"
    r = run("make_hash_list.py", "--preview", repo, sha, "luxodd/unity-plugin-development",
            "UnityPluginDevelopment", "1.3.0-preview.1", manifest)
    assert r.returncode == 0, r.stderr
    tar = tmp_path / "source.tar"
    subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "--prefix=luxodd-unity-plugin-development-abc/",
                    "-o", str(tar), sha], check=True)
    return manifest, tar, sha

def test_preview_list_records_channel_and_commit(preview):
    manifest, _, sha = preview
    m = json.loads(manifest.read_text())
    assert m["channel"] == "preview" and m["source"]["commit"] == sha and "package_sha256" not in m
    assert set(m["files"]) == set(PREVIEW_TREE)

def test_preview_install_and_verify_pass(project, preview):
    manifest, tar, _ = preview
    assert run("install_plugin.py", project, tar, manifest).returncode == 0
    r = run("verify_plugin.py", project, manifest)
    assert r.returncode == 0 and "(preview)" in r.stdout
    assert not (project / "Assets/Other.cs").exists()

def test_preview_verify_fails_on_one_changed_file(project, preview):
    manifest, tar, _ = preview
    run("install_plugin.py", project, tar, manifest)
    (project / "Assets/WebGLTemplates/LuxoddTemplate/index.html").write_bytes(b"<html>edited</html>\n")
    r = run("verify_plugin.py", project, manifest)
    assert r.returncode == 1 and "1 changed" in r.stdout

def test_preview_install_refuses_a_source_that_differs(tmp_path, project, preview):
    manifest, _, _ = preview
    src = tmp_path / "src"
    for rel, data in PREVIEW_TREE.items():
        p = src / "UnityPluginDevelopment" / rel
        p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    (src / "UnityPluginDevelopment/Assets/Luxodd.Game/Runtime/Core/PluginVersion.cs").write_bytes(b"tampered\n")
    r = run("install_plugin.py", project, src, manifest)
    assert r.returncode != 0 and "does not match" in r.stderr

def test_preview_list_without_a_commit_sha_is_rejected(tmp_path, project, preview):
    manifest, tar, sha = preview
    m = json.loads(manifest.read_text()); m["source"]["commit"] = "main"
    bad = tmp_path / "bad.json"; bad.write_text(json.dumps(m))
    for tool, args in (("install_plugin.py", (project, tar, bad)), ("verify_plugin.py", (project, bad))):
        r = run(tool, *args)
        assert r.returncode != 0 and "40-character commit SHA" in r.stderr
    r = run("make_hash_list.py", "--preview", tmp_path, "main", "luxodd/x", "UnityPluginDevelopment",
            "1.3.0-preview.1", tmp_path / "x.json")
    assert r.returncode != 0 and "40-character commit SHA" in r.stderr

# ---- post-build re-verify: importer re-serialized .meta files

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "import-rewrite")
SPRITES = ["white_circle_256_8_gradient.png.meta", "white_round_rect_16.png.meta"]
PLUGIN_META = (b"fileFormatVersion: 2\nguid: 0123456789abcdef0123456789abcdef\nPluginImporter:\n"
               b"  isPreloaded: 0\n  platformData:\n  - first:\n      WebGL: WebGL\n    second:\n      enabled: 1\n")
MONO_META = b"fileFormatVersion: 2\nguid: 11112222333344445555666677778888\nMonoImporter:\n  serializedVersion: 2\n"

@pytest.fixture
def rebuilt(tmp_path):
    """A project as installed (plus a baseline copy and its hash list), ready to be edited."""
    proj, base = tmp_path / "game", tmp_path / "plugin-baseline"
    files = {f"Assets/Luxodd.Game/Example/Sprites/{n}": open(os.path.join(FIXTURES, n + ".release"), "rb").read()
             for n in SPRITES}
    files["Assets/Luxodd.Game/Plugins/WebGL/websocket.jslib.meta"] = PLUGIN_META
    files["Assets/Luxodd.Game/Runtime/Core/PluginVersion.cs.meta"] = MONO_META
    files["Assets/Luxodd.Game/Runtime/Core/PluginVersion.cs"] = b'public const string Version = "1.2.0";\n'
    for root in (proj, base):
        for rel, data in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True); (root / rel).write_bytes(data)
    manifest = tmp_path / "list.json"
    manifest.write_text(json.dumps({"plugin": "luxodd/unity-plugin", "version": "1.2.0", "package_sha256": "0" * 64,
                                    "roots": ["Assets/Luxodd.Game"],
                                    "files": {r: hashlib.sha256(d).hexdigest() for r, d in files.items()}}))
    return proj, base, manifest

def reverify(proj, base, manifest, report):
    return run("verify_plugin.py", proj, manifest, "--report", report, "--allow-import-rewrites", base)

def rewrite_sprites(proj):
    for n in SPRITES:
        (proj / "Assets/Luxodd.Game/Example/Sprites" / n).write_bytes(open(os.path.join(FIXTURES, n + ".unity6000.6"), "rb").read())

def test_real_unity_sprite_meta_rewrites_pass_and_are_recorded(tmp_path, rebuilt):
    proj, base, manifest = rebuilt
    rewrite_sprites(proj)
    assert run("verify_plugin.py", proj, manifest).returncode == 1  # still byte-exact without the flag
    r = reverify(proj, base, manifest, tmp_path / "after.json")
    assert r.returncode == 0, r.stdout
    rep = json.loads((tmp_path / "after.json").read_text())
    assert sorted(x["path"].rsplit("/", 1)[1] for x in rep["import_rewrites"]) == SPRITES
    x = rep["import_rewrites"][0]
    assert x["importer"] == "TextureImporter" and x["old_sha256"] != x["new_sha256"]
    assert "internalIDToNameTable" in x["keys"] and "spriteTessellationMethod" in x["keys"]

def test_rewrite_with_a_changed_guid_fails(tmp_path, rebuilt):
    proj, base, manifest = rebuilt
    rewrite_sprites(proj)
    p = proj / "Assets/Luxodd.Game/Example/Sprites" / SPRITES[0]
    p.write_bytes(re.sub(rb"guid: [0-9a-f]+", b"guid: ffffffffffffffffffffffffffffffff", p.read_bytes()))
    r = reverify(proj, base, manifest, tmp_path / "after.json")
    assert r.returncode == 1 and "guid changed" in r.stdout

def test_rewrite_with_a_changed_importer_type_fails(tmp_path, rebuilt):
    proj, base, manifest = rebuilt
    p = proj / "Assets/Luxodd.Game/Example/Sprites" / SPRITES[1]
    p.write_bytes(p.read_bytes().replace(b"TextureImporter:", b"DefaultImporter:"))
    r = reverify(proj, base, manifest, tmp_path / "after.json")
    assert r.returncode == 1 and "importer changed" in r.stdout

def test_plugin_importer_meta_change_fails(tmp_path, rebuilt):
    proj, base, manifest = rebuilt
    p = proj / "Assets/Luxodd.Game/Plugins/WebGL/websocket.jslib.meta"
    p.write_bytes(PLUGIN_META.replace(b"enabled: 1", b"enabled: 0"))
    r = reverify(proj, base, manifest, tmp_path / "after.json")
    assert r.returncode == 1 and "code or plugin asset" in r.stdout

def test_code_asset_meta_and_code_changes_fail(tmp_path, rebuilt):
    proj, base, manifest = rebuilt
    (proj / "Assets/Luxodd.Game/Runtime/Core/PluginVersion.cs.meta").write_bytes(MONO_META + b"  executionOrder: -100\n")
    (proj / "Assets/Luxodd.Game/Runtime/Core/PluginVersion.cs").write_bytes(b"// patched\n")
    r = reverify(proj, base, manifest, tmp_path / "after.json")
    assert r.returncode == 1 and "2 changed" in r.stdout and "not a .meta file" in r.stdout

def test_a_baseline_that_differs_from_the_list_is_not_trusted(tmp_path, rebuilt):
    proj, base, manifest = rebuilt
    rewrite_sprites(proj)
    for n in SPRITES:  # an attacker "pre-rewrites" the baseline to match the tampered files
        (base / "Assets/Luxodd.Game/Example/Sprites" / n).write_bytes((proj / "Assets/Luxodd.Game/Example/Sprites" / n).read_bytes())
    r = reverify(proj, base, manifest, tmp_path / "after.json")
    assert r.returncode == 1 and "baseline copy does not match" in r.stdout

def test_predicate_records_import_rewrites(tmp_path, rebuilt):
    proj, base, manifest = rebuilt
    rewrite_sprites(proj)
    reverify(proj, base, manifest, tmp_path / "after.json")
    out = tmp_path / "build"; out.mkdir(); (out / "index.html").write_text("<html></html>")
    hooks = tmp_path / "hooks.json"; hooks.write_text(json.dumps({"findings": [], "ok": True}))
    r = run("build_manifest.py", out, manifest, tmp_path / "after.json", hooks, tmp_path / "pred.json")
    assert r.returncode == 0, r.stderr
    pred = json.loads((tmp_path / "pred.json").read_text())
    assert len(pred["plugin"]["importRewrites"]) == 2 and pred["plugin"]["channel"] == "release"
