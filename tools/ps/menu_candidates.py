"""Candidate script routes for every ps_menu command, from labels in the built-in terminology (not executed here).
    python menu_candidates.py   -> work/ps/menuinv/candidates.json {id: {"mit": [...], "ev": [...]}}"""
import json, re
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

W = (PGD / "work/ps")
T = json.loads((W / "ps_terminology.json").read_text(encoding="utf-8"))


def lab(z):
    return z["z"].split("=", 1)[1] if isinstance(z, dict) else str(z)


def norm(s):
    s = s.lower().replace("&&", "and").replace("&", "").replace("...", "").replace("\u2026", "")
    s = re.sub(r"\^<s\^>|[^a-z0-9% ]", " ", s)
    s = re.sub(r"\b(toggle|panel|palette|the|a)\b", " ", s)
    return " ".join(s.split())


MIT = {k: norm(lab(v)) for k, v in T["Enums"]["menuItemType"].items()}
EV = {k: norm(lab(v[0])) for k, v in T["Events"].items()}


def cands(item):
    title, parent = norm(item["name"]), norm(item["path"].rsplit("/", 2)[-2]) if item["path"].count("/") >= 2 else ""
    keys = {title, (parent + " " + title).strip(), (title + " " + parent).strip()}
    mit = [k for k, v in MIT.items() if v in keys or norm(k) in keys]
    ev = [k for k, v in EV.items() if v in keys]
    return {"mit": mit, "ev": ev}


if __name__ == "__main__":
    items = json.loads((PGD / "harvest/ps/ps_menu.json").read_text(encoding="utf-8"))["items"]
    out = {i["id"]: dict(cands(i), path=i["path"]) for i in items}
    (W / "menuinv" / "candidates.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(sum(1 for v in out.values() if v["mit"]), "with menuItemType,", sum(1 for v in out.values() if v["ev"]), "with event,",
          sum(1 for v in out.values() if not v["mit"] and not v["ev"]), "none")
