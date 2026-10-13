"""PGD/CDR: walk CorelDRAW 2024's LIVE menu bar through FrameWork.Automation and caption every entry.

    python menu_walk.py      -> work/cdr/menu_live.json  [{path, guid, caption, has_sub, bar, xml{...}}]

Live = Automation.GetNumItemsOnBar / GetItem(bar, i) / GetCaptionText(guid) on the running app, so the tree is what
this install shows (DrawUI.xml supplies the flyoutBarRef of each sub-menu and the item's bindings).
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdr_com import Corel  # noqa: E402
from drawui import UI  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "work" / "cdr" / "menu_live.json"
MENUBAR_MODE = "76d73481-9076-44c9-821c-52de9408cce2"   # menubar modeData used when a document is open


def clean(c):
    return (c or "").replace("&&", "\0").replace("&", "").replace("\0", "&").replace("...", "").strip()


def walk(cd, ui, top_guids):
    rows = []

    def job(app):
        au = app.FrameWork.Automation

        def rec(bar, path, depth):
            try:
                n = au.GetNumItemsOnBar(bar)
            except Exception as e:  # noqa: BLE001
                rows.append({"path": path, "bar": bar, "error": "GetNumItemsOnBar: " + str(e)[:120]})
                return
            for i in range(n):
                g, sub = au.GetItem(bar, i)
                x = ui.items.get(g)
                a = dict(x.attrib) if x is not None else {}
                if a.get("type") is None and x is not None and len(a) == 1:
                    continue  # separator
                cap = au.GetCaptionText(g)
                row = {"path": path + "/" + clean(cap) if path else clean(cap), "caption": cap, "guid": g,
                       "bar": bar, "has_sub": bool(sub), "type": a.get("type")}
                for k in ("onInvoke", "check", "flyoutBarRef", "items", "dynamicCategory"):
                    if k in a:
                        row[k] = a[k]
                rows.append(row)
                fb = a.get("flyoutBarRef")
                if sub and fb and depth < 6:
                    rec(fb, row["path"], depth + 1)

        for g in top_guids:
            x = ui.items[g]
            cap = au.GetCaptionText(g)
            rows.append({"path": clean(cap), "caption": cap, "guid": g, "bar": "menubar", "has_sub": True,
                         "type": "flyout", "flyoutBarRef": x.get("flyoutBarRef")})
            rec(x.get("flyoutBarRef"), clean(cap), 1)
        return len(rows)

    cd.call(job, timeout=300)
    return rows


def main():
    ui = UI()
    mode = next(m for m in ui.root.iter("modeData") if m.get("guid") == MENUBAR_MODE)
    tops = [i.get("guidRef") for i in mode.findall("item") if i.get("guidRef") in ui.items]
    rows = walk(Corel(), ui, tops)
    OUT.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(len(rows), "menu rows ->", OUT)


if __name__ == "__main__":
    main()
