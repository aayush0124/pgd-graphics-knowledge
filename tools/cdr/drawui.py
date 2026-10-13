"""PGD/CDR: read CorelDRAW 2024's Draw/UIConfig/DrawUI.xml (every command, menu and dialog control by GUID).

    from drawui import UI
    ui = UI()
    ui.menu_tree("21cd018a-87c1-476c-9a98-a8e36b9c479e")   # Effects menu -> nested [{guid, type, bind, children}]
    ui.ds_controls("GaussianBlurEffectDS")                  # dialog controls bound to that data source -> params

    python drawui.py [bar_guid]     print a menu tree (default: Effects)
"""
import re, sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(r"C:/Program Files/Corel/CorelDRAW Graphics Suite/25")
XML = ROOT / "Draw" / "UIConfig" / "DrawUI.xml"
STRINGS = ROOT / "Languages" / "EN" / "Data" / "strings.xml"
EFFECTS_BAR = "21cd018a-87c1-476c-9a98-a8e36b9c479e"   # commandBarData nonLocalizableName="Effects" (menubar flyout)

BIND = re.compile(r"DataSource=([A-Za-z0-9_]+);Path=([^;)]+)")
VALUE_ATTRS = ("value", "check", "currentActiveOfGroup", "currentItem", "currentSelection", "text", "color", "items")


def workspace_root(ws_dir=None, name="_default"):
    """The ACTIVE workspace (user copy <UserWorkspacePath>/<name>.cdws = zip with content/workspace.xml). It overrides
    DrawUI.xml for shortcuts and toolbar contents (Application.ActiveWorkspace.Name gives <name>). -> Element|None"""
    import zipfile
    d = Path(ws_dir) if ws_dir else Path.home() / "AppData/Roaming/Corel/CorelDRAW Graphics Suite 2024/Draw/Workspace"
    p = d / f"{name}.cdws"
    return ET.fromstring(zipfile.ZipFile(p).read("content/workspace.xml")) if p.exists() else None


def bind_of(s):
    """'*Bind(DataSource=X;Path=Y;...)' -> (X, Y) or None (first binding only)."""
    m = BIND.search(s or "")
    return (m.group(1), m.group(2)) if m else None


def num(s):
    try:
        f = float(str(s).split()[0])
        return int(f) if f.is_integer() and "." not in str(s) else f
    except (ValueError, IndexError):
        return None


class UI:
    def __init__(self, path=XML):
        self.root = ET.parse(path).getroot()
        self.items = {e.get("guid"): e for e in self.root.iter("itemData")}
        self.bars = {e.get("guid"): e for e in self.root.iter("commandBarData")}
        self.strings = {}
        if STRINGS.exists():
            for e in ET.parse(STRINGS).getroot():
                self.strings[e.get("guid")] = e.text or ""

    # ---- menus -------------------------------------------------------------------------------------------------
    def bar_items(self, bar_guid):
        bar = self.bars.get(bar_guid)
        if bar is None:
            return []
        menu = bar.find("menu")
        if menu is None:
            menu = bar.find(".//toolbar")
        return [] if menu is None else [i.get("guidRef") for i in menu.findall("item")]

    def menu_tree(self, bar_guid, depth=0, seen=None):
        seen = set() if seen is None else seen
        out = []
        for g in self.bar_items(bar_guid):
            e = self.items.get(g)
            node = {"guid": g}
            if e is None:
                node["type"] = "missing"
            else:
                a = dict(e.attrib)
                node["type"] = a.get("type") or "separator"
                for k in ("onInvoke", "check", "flyoutBarRef", "captionRef", "dynamicCategory", "items",
                          "enable", "newForVersion", "visible"):
                    if k in a:
                        node[k] = a[k]
                fb = a.get("flyoutBarRef")
                if fb and fb not in seen and depth < 6:
                    seen.add(fb)
                    node["children"] = self.menu_tree(fb, depth + 1, seen)
            out.append(node)
        return out

    # ---- dialog controls --------------------------------------------------------------------------------------
    def ds_controls(self, ds):
        """All itemData controls whose value-ish attribute binds to DataSource=ds. -> list of dicts."""
        out = []
        for g, e in self.items.items():
            a = e.attrib
            hit = None
            for k in VALUE_ATTRS:
                b = bind_of(a.get(k))
                if b and b[0] == ds:
                    hit = (k, b[1])
                    break
            if not hit:
                continue
            c = {"guid": g, "control": a.get("type"), "attr": hit[0], "path": hit[1]}
            for k in ("rangeMin", "rangeMax", "increment", "numDecimalPlaces", "identifier", "captionRef",
                      "transform", "displayUnit", "internalUnit", "showUnit", "length"):
                if k in a:
                    c[k] = a[k]
            for k in ("items", "currentItem"):
                if k in a and k != hit[0]:
                    c[k] = a[k]
            out.append(c)
        return out

    def label_for(self, guid):
        """statusText items that show *CT('<guid>') are that control's label -> their guid (caption source)."""
        pat = f"*CT('{guid}')"
        return [g for g, e in self.items.items() if e.get("type") == "statusText" and e.get("text") == pat]


def params_from_controls(ctrls):
    """Collapse slider+spinner pairs and radio groups into one param per data-source path."""
    by = {}
    for c in ctrls:
        p = c["path"]
        if c["attr"] == "check" and p.startswith("ApplyOrDeleteEffect"):
            continue
        d = by.setdefault(p, {"key": p, "controls": []})
        d["controls"].append(c["control"])
        for k in ("rangeMin", "rangeMax"):
            v = c.get(k)
            if v is None:
                continue
            if v.startswith("*"):
                b = bind_of(v)
                if b:
                    d.setdefault(k + "Bind", b[1])
            elif num(v) is not None:
                d.setdefault(k, num(v))
        for k in ("increment", "numDecimalPlaces", "transform", "displayUnit"):
            if k in c:
                d.setdefault(k, c[k])
        if c["control"] == "groupedRadioButton" and "identifier" in c:
            d.setdefault("enum", []).append({"value": c["identifier"], "guid": c["guid"],
                                             "captionRef": c.get("captionRef")})
        d.setdefault("guids", []).append(c["guid"])
    return list(by.values())


if __name__ == "__main__":
    import json
    ui = UI()
    print(json.dumps(ui.menu_tree(sys.argv[1] if len(sys.argv) > 1 else EFFECTS_BAR), indent=1))
