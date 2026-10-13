"""Extract Photoshop's built-in Action Manager terminology dictionary from Photoshop.exe.

Photoshop.exe carries its scripting dictionary as one PostScript-like text (split into null-separated chunks):
    <</Version 1/Events<</gaussianBlur [($$$/Actions/Event/GaussianBlur=Gaussian Blur) /imageReference
        <</radius [($$$/Actions/Key/...=Radius) /unitFloat]>>] ...>> /Classes <<...>> /Enumerations? <<...>> ...>>
This parses it -> work/ps/ps_terminology.json  {top-level-key: {name: parsed}}.
Names in the dictionary are Action Manager stringIDs; (zstrings) carry the English display names.

    python ps_terminology.py            # writes the json, prints the section sizes
"""
import json, mmap, re, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

EXE = os.environ.get("PGD_PS_EXE") or r"C:/Program Files/Adobe/Adobe Photoshop 2026/Photoshop.exe"
OUT = (PGD / "work/ps/ps_terminology.json")


def raw_text(exe=EXE):
    with open(exe, "rb") as f:
        m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        s = m.find(b"<</Version 1/Events<<")
        if s < 0:
            raise SystemExit("terminology dictionary not found in " + exe)
        parts, pos, depth = [], s, 0
        while True:
            e = m.find(b"\0", pos)
            chunk = m[pos:e]
            parts.append(chunk)
            depth += chunk.count(b"<<") - chunk.count(b">>") + chunk.count(b"[") - chunk.count(b"]")
            pos = e
            while m[pos] == 0:
                pos += 1
            if depth <= 0 or len(parts) > 400:
                break
    return b"".join(parts).decode("latin-1")


TOK = re.compile(r"\s*(<<|>>|\[|\]|\((?:[^()\\]|\\.)*\)|/[^\s/\[\]<>()]*|[^\s/\[\]<>()]+)")


def parse(text):
    toks = [t for t in TOK.findall(text) if t]
    i = 0

    def val():
        nonlocal i
        t = toks[i]
        i += 1
        if t == "<<":
            d = {}
            while toks[i] != ">>":
                k = toks[i]
                i += 1
                d[k[1:] if k.startswith("/") else k] = val()
            i += 1
            return d
        if t == "[":
            a = []
            while toks[i] != "]":
                a.append(val())
            i += 1
            return a
        if t.startswith("("):
            return {"z": t[1:-1]}
        if t.startswith("/"):
            return t  # keep the slash: a name reference
        return t
    return val()


def zname(z):
    """'$$$/Actions/Key/Blur/Angle=Angle' -> 'Angle'"""
    s = z["z"] if isinstance(z, dict) else str(z)
    s = s.split("=", 1)[1] if "=" in s else s
    return re.sub(r"&(?!&)", "", s).replace("&&", "&")  # drop menu accelerators


if __name__ == "__main__":
    txt = raw_text()
    (OUT.parent / "ps_terminology_raw.txt").write_text(txt, encoding="utf-8")
    tree = parse(txt)
    OUT.write_text(json.dumps(tree, indent=0), encoding="utf-8")
    print(len(txt), "chars;", {k: (len(v) if isinstance(v, (dict, list)) else v) for k, v in tree.items()})
    ev = tree.get("Events", {})
    for k in ("gaussianBlur", "surfaceBlur", "motionBlur", "addNoise"):
        print(k, json.dumps(ev.get(k))[:400])
