"""PGD / Illustrator: open Edit > Keyboard Shortcuts (executeMenuCommand "KBSC Menu Item") and dump the dialog's UI
Automation tree -> work/ai/kbsc/uia_tree.txt, then cancel it (Escape posted to the dialog's handle)."""
import sys, threading, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

import uiautomation as auto

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aicom import js, dialogs, u32  # noqa: E402

OUT = (PGD / "work/ai/kbsc")


def dump(c, depth=0, lines=None, maxd=12):
    lines = [] if lines is None else lines
    r = c.BoundingRectangle
    lines.append("  " * depth + f"{c.ControlTypeName} name={c.Name!r} aid={c.AutomationId!r} cls={c.ClassName!r} "
                 f"hwnd={c.NativeWindowHandle} rect=({r.left},{r.top},{r.right},{r.bottom})")
    if depth < maxd:
        for ch in c.GetChildren():
            dump(ch, depth + 1, lines, maxd)
    return lines


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    box = {}
    t = threading.Thread(target=lambda: box.update(r=js('app.executeMenuCommand("KBSC Menu Item"); "closed";', 300)),
                         daemon=True)
    t.start()
    dlg = None
    for _ in range(60):
        time.sleep(0.5)
        ds = [d for d in dialogs() if d[3]]
        if ds:
            dlg = ds[0]
            break
    if not dlg:
        print("no dialog")
        return
    time.sleep(1.5)
    print("dialog", dlg)
    with auto.UIAutomationInitializerInThread():
        c = auto.ControlFromHandle(dlg[0])
        lines = dump(c)
    (OUT / "uia_tree.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:80]))
    print(len(lines), "nodes")
    if "--keep" not in sys.argv:
        for msg in (0x100, 0x101):
            u32.PostMessageW(dlg[0], msg, 0x1B, 0)
        t.join(20)
        print("after cancel:", box, [d for d in dialogs()])


if __name__ == "__main__":
    main()
