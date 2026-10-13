"""Dump Photoshop's whole menu tree (menuBarInfo) -> work/ps/menu_tree.json: [{name, command, path, enabled?}]."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import psdrv  # noqa: E402

JS = r"""
(function () {
  var r = new ActionReference();
  r.putProperty(C2T("Prpr"), S2T("menuBarInfo"));
  r.putEnumerated(C2T("capp"), C2T("Ordn"), C2T("Trgt"));
  var root = executeActionGet(r).getObjectValue(S2T("menuBarInfo"));
  var out = [];
  function walk(d, path) {
    var name = d.hasKey(S2T("name")) ? d.getString(S2T("name")) : "";
    var rec = {name: name, path: path ? path + "/" + name : name};
    if (d.hasKey(S2T("command"))) rec.command = d.getInteger(S2T("command"));
    var keys = []; for (var i = 0; i < d.count; i++) keys.push(tid2s(d.getKey(i)));
    rec.keys = keys.join(",");
    if (d.hasKey(S2T("enabled"))) rec.enabled = d.getBoolean(S2T("enabled"));
    var f = ["title", "menuID", "kind", "iconName"];
    for (var q = 0; q < f.length; q++) if (d.hasKey(S2T(f[q]))) try { var v = dval(d, S2T(f[q]), 0); rec[f[q]] = v.v; } catch (e0) {}
    if (d.hasKey(S2T("visible"))) rec.visible = d.getBoolean(S2T("visible"));
    if (d.hasKey(S2T("menuShortcut"))) try {
      var m = d.getObjectValue(S2T("menuShortcut")), sc = "";
      if (m.hasKey(S2T("keyChar"))) {
        if (m.getBoolean(S2T("commandKey"))) sc += "Ctrl+";
        if (m.getBoolean(S2T("optionKey"))) sc += "Alt+";
        if (m.getBoolean(S2T("shiftKey"))) sc += "Shift+";
        if (m.getBoolean(S2T("controlKey"))) sc += "Win+";
        rec.shortcut = sc + m.getString(S2T("keyChar"));
      }
    } catch (e) {}
    var sub = d.hasKey(S2T("submenu")) ? d.getList(S2T("submenu")) : null;
    rec.n_sub = sub ? sub.count : 0;
    out.push(rec);
    if (sub) for (var j = 0; j < sub.count; j++) walk(sub.getObjectValue(j), rec.path);
  }
  walk(root, "");
  return J(out);
})();
"""

if __name__ == "__main__":
    tree = psdrv.jsj(JS, timeout=120, tag="menus")
    out = psdrv.WORK / "menu_tree.json"
    out.write_text(json.dumps(tree, indent=1), encoding="utf-8")
    print(len(tree), "nodes ->", out)
