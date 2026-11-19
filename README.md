# luxodd/game-build

Reusable GitHub Actions workflow that builds a Luxodd game with the official, untampered
plugin and signs the result, without Luxodd seeing the game's source. Design:
`~/projects/docs/design/plugin-attestation-design.md`.

**Status, 2026-11-19:** draft, in the **private** GitHub repo `luxodd/game-build` (draft PR #1).
The Unity workflow has not run on GitHub yet; the Python tools and their tests run locally and
in this repo's own CI.

**Relation to `luxodd/global-ci`.** global-ci PR #2 (`unity-webgl-deploy.yml`, open since July)
is a reusable GameCI WebGL build that deploys to staging and production. This workflow reuses
its patterns: actions pinned by commit, the `runner` input (hosted, Ubicloud or self-hosted),
the Library cache, and checking out its own scripts at `job.workflow_sha`. It differs on
purpose: it installs and verifies the official plugin, signs the build, and **never deploys**.
Uploads go to a game's draft (LUXL-2710); promotion stays a human approval. If PR #2 lands, its
deploy job should consume this workflow's signed artifact rather than build its own.

## Layout

| Path | What it is |
| --- | --- |
| `.github/workflows/unity-webgl.yml` | the reusable workflow (`on: workflow_call`) |
| `examples/caller-unity.yml` | the one file a game repo adds |
| `.github/workflows/attest-test.yml` | attest-only reusable workflow: signs a dummy artifact, for proving the signing and verify path without Unity |
| `examples/caller-attest-test.yml` | its caller, for a public test repo on GitHub-hosted runners |
| `plugin-manifests/unity/<version>.json` | published hash list per plugin release: package sha256 plus sha256 of every installed file and `.meta` |
| `tools/make_hash_list.py` | writes a hash list from a release `.unitypackage` |
| `tools/install_plugin.py` | deletes the project's plugin folders and installs the pinned package, refusing a package whose hash is not the list's |
| `tools/verify_plugin.py` | byte-exact check of the project's plugin folders against a hash list |
| `tools/scan_build_hooks.py` | fails on editor build callbacks that name the plugin; lists other hooks for review |
| `tools/build_manifest.py` | writes the signed predicate: source, plugin, check results, settings, every build file's hash |
| `tools/extract_unitypackage.py` | unpacks a `.unitypackage` to real paths (for diffs) |
| `unity-build/Editor/LuxoddWebGLBuild.cs` | the build method; fixed settings, one graphics target |
| `tests/` | `python -m pytest tests -q` (synthetic package; no Unity, no network) |

## What a run does

1. Checks out its own scripts at `job.workflow_sha`, so a caller pinned to a SHA gets exactly
   those scripts.
2. Downloads `luxodd/unity-plugin` release `v<version>` and refuses it unless its sha256 is
   the hash list's.
3. Deletes `Assets/Luxodd.Game` and `Assets/WebGLTemplates/LuxoddTemplate`, installs the
   package, verifies every file.
4. Scans for build hooks. **fail:** a build callback in a file that names the plugin.
   **review:** any other callback, `[DidReloadScripts]`, or editor code that names the plugin
   and writes files.
5. Builds with GameCI (`unity: gameci`, Docker) or with the runner's own installed editor
   (`unity: local`, the exact `ProjectVersion.txt` version, never a substitute). Both run
   the same build method: `LuxoddTemplate`, Gzip, threads off, non-development, one graphics
   target (`webgl2` or `webgpu`), the project's own Unity version.
6. Re-verifies the plugin, hashes every build file, signs: GitHub artifact attestation, or
   cosign keyless for private repos without Enterprise Cloud.

Verify a GitHub-signed build:

```bash
gh attestation verify <file> --repo <owner>/<game> --signer-repo luxodd/game-build
```

## Measured locally

- Hash lists generated for every full-version Unity release, 1.0.3 to 1.2.0 (1.0.5 omitted:
  its package reports itself as 1.0.4).
- `plugin-manifests/unity/1.2.0.json` re-checked 2026-11-19 against a fresh download of the
  `v1.2.0` release: package sha256 `cad97c1a…39e8` matches, and the regenerated list is
  identical (602 files).
- Tower Rush dry run, 2026-11-19, on an APFS clone of `feat/platform-layout-4x3` (no Unity).
  Before install, against 1.2.0: 568 of 602 files changed (558 only line endings or whitespace,
  2 `.meta`, 8 real content: the 1.3.0-preview.1 network and version files, CHANGELOG,
  `NetworkSettingsDescriptor.asset`, template `index.html`), 1 missing, 8 added. Install wrote
  269 files; afterwards 602 of 602 verify. Hook scan: 0 fail, 5 review (Spine
  `SpineBuildProcessor` and `EditorSkeletonPlayer`, Zenject `TestBuildAssemblyFilter`,
  post-processing `[DidReloadScripts]` ×2), 6 editor DLLs unscanned (DOTween ×2, Zenject Cecil
  ×4).
- Hook scan over all 22 games: 2 fail (gravity-switch-game `WebGLReleaseGuard.cs`,
  parabox-game `ParaboxLuxoddWebGLBuildGuard.cs`), the rest pass with review items.

## Known gaps before this can be published

- **Unity licences on GitHub runners** (design open issue). Nothing has been activated.
- **Template.** The build forces `LuxoddTemplate`. Two games and Tower Rush's `main` still use
  `TemplateWithInstance`; Tower Rush's `feat/platform-layout-4x3` already uses `LuxoddTemplate`.
- **Tower Rush needs an unreleased plugin.** `feat/platform-layout-4x3` carries plugin
  1.3.0-preview.1, and four game scripts call its tournament APIs (`TournamentInfo*`), which
  1.2.0 does not have. Installing 1.2.0 over it verifies (602 of 602) but the game will not
  compile. An attested Tower Rush build needs a published 1.3.0 (or preview) release and its
  hash list, or a branch without the tournament code.
- **Install overwrites `Resources/NetworkSettingsDescriptor.asset`.** It is a plugin file, so
  the game's own settings in it are replaced by the release's. Games must not depend on
  editing it (the committed API keys belong elsewhere anyway).
- **API updater.** On Unity 6, Unity rewrites `velocity` to `linearVelocity` in a plugin
  example script when it updates APIs. If GameCI's import applies that, the post-build
  re-verify fails for every Unity 6 game. Fix in the plugin (version-guarded code), not by
  loosening the check. Not yet observed in a real run.
- **Game code that calls changed plugin internals** will not compile against the pinned plugin.
  Expected for games with edited plugin files; that is the migration, not a workflow bug.
- **Older plugin versions** install extra folders (`Assets/Fonts`, `Assets/TextMesh Pro`) that
  can overwrite the project's own. Only allow 1.2.0 until that is handled.
- Decide where the hash lists are published (this repo, or release assets of
  `luxodd/unity-plugin` signed by its release workflow).
- **Private repos need cosign.** GitHub attestations on private repos need Enterprise Cloud,
  and global-ci notes the org is not even on Team. So `signing: cosign` is the default path for
  private game repos until that changes.
- **Local Unity path untested.** `unity: local` (no Docker) is written but has not run; the
  runner's editor must be licensed and match `ProjectVersion.txt` exactly.
- **The repo is private.** Callers in other repos can use a reusable workflow from a private
  repo only with the org's Actions access setting; the design assumes a public repo.
- **Admin check.** Not built. Design: `~/projects/docs/design/attestation-upload-check.md`.
- Godot and luxodd.js variants (workstream B step 5).
