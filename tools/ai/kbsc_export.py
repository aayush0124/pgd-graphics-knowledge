"""PGD / Illustrator: Edit > Keyboard Shortcuts > Export Text... -> work/ai/kbsc/kbsc_export.txt

The dialog opens through executeMenuCommand("KBSC Menu Item"); every button press is a UI Automation Invoke on the
dialog's own element (no global keyboard / mouse input, so no host lock). The Save dialog's file-name box is set
through its ValuePattern. The shortcuts dialog is closed with its Cancel button: no preference changes.
"""
import sys, threading, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

import uiautomation as auto

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aicom import js, dialogs, u32  # noqa: E402

OUT = (PGD / "work/ai/kbsc")
TXT = OUT / "kbsc_export.txt"


def wait_dialog(pred, secs=30):
    for _ in range(int(secs / 0.25)):
        ds = [d for d in dialogs() if d[3] and pred(d)]
        if ds:
            return ds[0]
        time.sleep(0.25)
    return None


def invoke_async(ctrl):
    """Invoke may not return until a modal opened by the button closes: run it in its own thread."""
    def run():
        with auto.UIAutomationInitializerInThread():
            ctrl.GetInvokePattern().Invoke()
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if TXT.exists():
        TXT.unlink()
    box = {}
    t = threading.Thread(target=lambda: box.update(r=js('app.executeMenuCommand("KBSC Menu Item"); "closed";', 300)),
                         daemon=True)
    t.start()
    kb = wait_dialog(lambda d: d[2] == "Keyboard Shortcuts")
    if not kb:
        raise SystemExit("Keyboard Shortcuts dialog did not open")
    time.sleep(1.5)
    with auto.UIAutomationInitializerInThread():
        w = auto.ControlFromHandle(kb[0])
        exp = w.ButtonControl(Name="Export Text...", searchDepth=4)
        invoke_async(exp)
        sv = wait_dialog(lambda d: d[0] != kb[0], 30)
        print("save dialog:", sv)
        if not sv:
            raise SystemExit("no save dialog")
        time.sleep(1.0)
        s = auto.ControlFromHandle(sv[0])
        # common file dialog: file name edit is the combo's edit (aid 1001) / Edit named 'File name:'
        ed = s.EditControl(AutomationId="1001", searchDepth=8)
        if not ed.Exists(3):
            ed = s.EditControl(Name="File name:", searchDepth=8)
        ed.GetValuePattern().SetValue(str(TXT).replace("/", "\\"))
        time.sleep(0.3)
        btn = s.ButtonControl(AutomationId="1", searchDepth=4)
        print("save button:", btn.Name)
        invoke_async(btn)
        for _ in range(40):
            time.sleep(0.25)
            if TXT.exists() and TXT.stat().st_size > 0:
                break
        time.sleep(1.0)
        left = [d for d in dialogs() if d[0] not in (kb[0],)]
        print("left after save:", left)
        for d in left:  # e.g. an overwrite confirmation: cancel it
            for msg in (0x100, 0x101):
                u32.PostMessageW(d[0], msg, 0x1B, 0)
        time.sleep(0.5)
        cancel = w.ButtonControl(Name="Cancel", searchDepth=3)
        invoke_async(cancel)
    t.join(30)
    print("kbsc dialog closed:", box, "dialogs now:", dialogs())
    print(TXT, TXT.stat().st_size if TXT.exists() else "MISSING")


if __name__ == "__main__":
    main()
