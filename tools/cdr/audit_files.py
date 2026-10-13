"""PGD/CDR independent audit (file part): every file under the preset folders of the install vs the files that
cdr_preset.json references (invoke.file or a path in extra). -> work/cdr/audit_preset_unref.json + printed table.

    python audit_files.py
"""
import collections, json, os
from pathlib import Path

PGD = Path(__file__).resolve().parents[2]
R = Path(r"C:/Program Files/Corel/CorelDRAW Graphics Suite/25")
DIRS = ["Draw/Presets", "Color", "Content", "Custom Data", "Draw/CustomMediaStrokes", "Data", "Draw/Workspace",
        "Draw/Envelope Presets.env", "Draw/linestyles.dot", "Draw/outlineWidths.xml"]


def norm(p):
    return os.path.normcase(os.path.normpath(str(p)))


def referenced(items):
    out = set()

    def add(v):
        if isinstance(v, str) and len(v) > 3 and v[1:3] in (":\\", ":/"):
            out.add(norm(v))
        elif isinstance(v, list):
            for x in v:
                add(x)
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
    for it in items:
        add((it.get("invoke") or {}).get("file"))
        add(it.get("extra") or {})
    return out


def main():
    items = json.loads((PGD / "harvest/cdr/cdr_preset.json").read_text(encoding="utf-8"))["items"]
    files = referenced(items)
    cnt, miss = collections.Counter(), collections.defaultdict(list)
    for d in DIRS:
        p = R / d
        for f in ([p] if p.is_file() else [x for x in p.rglob("*") if x.is_file()]):
            rel = f.relative_to(R).as_posix()
            top = "/".join(rel.split("/")[:2])
            cnt[(top, "disk")] += 1
            if norm(f) in files:
                cnt[(top, "harv")] += 1
            else:
                miss[top].append(rel)
    for k in sorted({k for k, _ in cnt}):
        print(f"{k:45s} disk {cnt[(k, 'disk')]:5d} referenced {cnt[(k, 'harv')]:5d}")
    (PGD / "work/cdr/audit_preset_unref.json").write_text(json.dumps(miss, indent=1), encoding="utf-8")
    for k, v in miss.items():
        exts = collections.Counter(Path(x).suffix.lower() for x in v)
        print("UNREF", k, len(v), dict(exts), v[:5])


if __name__ == "__main__":
    main()
