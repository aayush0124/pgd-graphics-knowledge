"""PGD: split the harvest into agent-sized batch files -> work/batches/<kind>_<nn>.json

    python prepare_batches.py            all kinds
    python prepare_batches.py ps_filter  just these kinds

Each batch item is the harvested item unchanged (name, id, path, params with types / ranges / defaults, invoke ...):
that is everything a card writer may rely on. Batches stay within a category where they can, so one agent sees a
family (all Blur filters) together.
"""
import json, os, sys
from pathlib import Path

HERE = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parent)
OUT = HERE / "work" / "batches"
VISUAL = {"ps_filter", "ps_adjustment", "ps_layer_style", "ps_blend_mode", "ai_effect", "ai_blend_mode", "cdr_effect"}
SIZE = {"tool": 15, "menu": 30, "preset": 40, "api": 40}  # api batches are then cut to ~400 members (split_api)


def tier(kind):
    return "visual" if kind in VISUAL else kind.split("_", 1)[1]


def size(kind):
    return 10 if kind in VISUAL else SIZE.get(tier(kind), 20)


def batches(items, n, kind):
    """Fill batches to n, cutting at a category change when the batch is at least half full."""
    out, cur = [], []
    for it in items:
        if cur and (len(cur) >= n or (len(cur) >= n // 2 and it.get("category") != cur[-1].get("category"))):
            out.append(cur)
            cur = []
        cur.append(it)
    if cur:
        out.append(cur)
    if kind.endswith("_api"):  # an API batch is sized by its members, not its classes
        out = [b2 for b in out for b2 in split_api(b)]
    return out


def split_api(b, budget=400):
    res, cur, m = [], [], 0
    for it in b:
        k = len((it.get("extra") or {}).get("members") or []) + len((it.get("extra") or {}).get("values") or []) + 1
        if cur and m + k > budget:
            res.append(cur)
            cur, m = [], 0
        cur.append(it)
        m += k
    return res + ([cur] if cur else [])


def plan(doc):
    """One harvest document -> [(batch name, batch document)], exactly what main() writes."""
    kind = doc["kind"]
    items = sorted(doc["items"], key=lambda x: ((x.get("category") or "~").lower(), (x.get("path") or "").lower(),
                                                x["name"].lower()))
    # API enums and library entries are lookup data: skeleton_cards.py writes their cards ("x" batches)
    det = [it for it in items if kind.endswith("_api") and it["id"].split(":")[0] in ("enum", "lib", "am")]
    items = [it for it in items if it not in det]
    bs = batches(items, size(kind), kind)
    named = [(f"{kind}_{k:02d}", b) for k, b in enumerate(bs, 1)]
    named += [(f"{kind}_x{k:02d}", det[i:i + 100]) for k, i in enumerate(range(0, len(det), 100), 1)]
    return [(name, {"kind": kind, "app": doc["app"], "tier": tier(kind), "app_version": doc.get("app_version"), "items": b})
            for name, b in named]


def all_batches(root=HERE):
    """Every batch, built in memory from root/harvest (no work/ folder needed): {name: batch document}."""
    return {n: b for f in sorted((Path(root) / "harvest").glob("*/*.json"))
            for n, b in plan(json.loads(f.read_text(encoding="utf-8")))}


def main(only):
    OUT.mkdir(parents=True, exist_ok=True)
    counts = {}
    for f in sorted((HERE / "harvest").glob("*/*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        kind = doc["kind"]
        if only and kind not in only:
            continue
        for old in OUT.glob(f"{kind}_*.json"):
            old.unlink()
        named = plan(doc)
        for name, b in named:
            (OUT / f"{name}.json").write_text(json.dumps(b, indent=1, ensure_ascii=False), encoding="utf-8")
        counts[kind] = (len(doc["items"]), len(named))
    for k, (n, b) in counts.items():
        print(f"{k:16s} {n:5d} items  {b:3d} batches")
    print(f"total {sum(n for n, _ in counts.values())} items, {sum(b for _, b in counts.values())} batches")


if __name__ == "__main__":
    main(set(sys.argv[1:]))
