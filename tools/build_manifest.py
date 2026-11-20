"""Write the attestation predicate for a finished build.

usage: build_manifest.py <build-dir> <plugin-manifest.json> <plugin-report.json> \
                         <hook-report.json> <out.json>

Records the plugin version and the sha256 of its hash list, the plugin and hook check results,
the build settings the build script wrote, and the sha256 of every build file. Repository,
commit and workflow identity come from the GitHub Actions environment; the signature itself
(GitHub attestation or cosign) binds them independently.
"""
import hashlib, json, os, sys

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    build, plugin_manifest, plugin_report, hook_report, out = sys.argv[1:6]
    files = {}
    for d, _, fs in os.walk(build):
        for f in fs:
            p = os.path.join(d, f)
            files[os.path.relpath(p, build).replace(os.sep, "/")] = sha256(p)
    settings_path = os.path.join(build, "luxodd-build-settings.json")
    pm = json.load(open(plugin_manifest))
    env = os.environ.get
    predicate = {
        "schema": "https://luxodd.com/game-build/v0",
        "source": {"repository": env("GITHUB_REPOSITORY"), "commit": env("GITHUB_SHA"),
                   "ref": env("GITHUB_REF")},
        "workflow": {"run_id": env("GITHUB_RUN_ID"), "run_attempt": env("GITHUB_RUN_ATTEMPT"),
                     "game_build_sha": env("LUXODD_GAME_BUILD_SHA"),
                     # gameci (Docker) or local (the runner's own Unity editor), and the runner
                     # kind, so a verifier can require a hosted build if it wants to.
                     "builder": env("LUXODD_BUILDER"),
                     "runner_environment": env("RUNNER_ENVIRONMENT")},
        "plugin": {"name": pm["plugin"], "version": pm["version"],
                   # "release": installed from a published package; "preview": from the
                   # plugin repo at a pinned commit (admin may treat these differently).
                   "channel": pm.get("channel", "release"),
                   "source": pm.get("source"),
                   "package_sha256": pm.get("package_sha256"),
                   "hash_list_sha256": sha256(plugin_manifest),
                   "check": json.load(open(plugin_report))},
        "build_hooks": json.load(open(hook_report)),
        "settings": json.load(open(settings_path)) if os.path.exists(settings_path) else None,
        "files": dict(sorted(files.items())),
        "total_bytes": sum(os.path.getsize(os.path.join(build, f)) for f in files),
    }
    with open(out, "w") as f:
        json.dump(predicate, f, indent=1)
        f.write("\n")
    print(f"{out}: {len(files)} build files, {predicate['total_bytes']} bytes")

if __name__ == "__main__":
    main()
