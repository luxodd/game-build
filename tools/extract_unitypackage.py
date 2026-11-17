"""Extract a .unitypackage (tar.gz of <guid>/{pathname,asset,asset.meta}) to real paths."""
import sys, tarfile, os, io
pkg, out = sys.argv[1], sys.argv[2]
entries = {}
with tarfile.open(pkg, "r:gz") as t:
    for m in t.getmembers():
        if not m.isfile():
            continue
        parts = m.name.lstrip("./").split("/")
        if len(parts) != 2:
            continue
        guid, kind = parts
        entries.setdefault(guid, {})[kind] = t.extractfile(m).read()
n = 0
for guid, e in entries.items():
    if "pathname" not in e:
        continue
    rel = e["pathname"].decode("utf-8").splitlines()[0].strip()
    if ".." in rel.split("/"):
        continue
    dst = os.path.join(out, rel)
    if "asset" in e:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(e["asset"]); n += 1
    else:
        os.makedirs(dst, exist_ok=True)
    if "asset.meta" in e:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        open(dst + ".meta", "wb").write(e["asset.meta"])
print(f"{pkg}: {n} files")
