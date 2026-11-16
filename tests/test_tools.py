"""Unit tests for the plugin install, hash check and build-hook scan.

Run: python -m pytest pipeline/game-build/tests -q
Uses a tiny synthetic .unitypackage, so it needs no Unity and no network.
"""
import hashlib, io, json, os, subprocess, sys, tarfile
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
