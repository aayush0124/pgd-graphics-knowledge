"""PGD: contact sheets for card writers / verifiers -> work/sheets/<batch>_s<n>.png + <batch>_sheets.json

    python make_sheets.py ps_preset_03 ...        named batches
    python make_sheets.py --kind ps_preset        every batch of a kind

Each sheet is a 5 x 4 grid of thumbnails (cell = the item's number in the batch + a short name), so one Read shows 20
items. Thumbnails come from gallery/<kind>/index.json (key = sha1(id)[:12], never a list position). Items without
a thumbnail get a grey cell saying why (failed / not renderable / missing).
"""
import hashlib, json, os, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parent)
COLS, ROWS, CELL, LABEL = 5, 4, 300, 36
try:
    FONT = ImageFont.truetype(os.environ.get("PGD_FONT") or "C:/Windows/Fonts/arial.ttf", 15)
except OSError:  # no Arial (Linux / macOS): Pillow's built-in face
    FONT = ImageFont.load_default()


def key(item_id):
    return hashlib.sha1(item_id.encode("utf-8")).hexdigest()[:12]


def gallery(kind):
    g = HERE / "gallery" / kind
    load = lambda n: json.loads((g / n).read_text(encoding="utf-8")) if (g / n).exists() else {}
    idx = {x["id"]: x for x in load("index.json") or []}
    return g, idx, load("failed.json"), load("not_renderable.json") | load("not_rendered.json")  # preset / effect galleries


def sheets(batch_name):
    b = json.loads((HERE / "work" / "batches" / f"{batch_name}.json").read_text(encoding="utf-8"))
    g, idx, failed, nr = gallery(b["kind"])
    out_dir = HERE / "work" / "sheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    per = COLS * ROWS
    meta = []
    for s in range(0, len(b["items"]), per):
        im = Image.new("RGB", (COLS * CELL, ROWS * (CELL + LABEL)), "#FFFFFF")
        d = ImageDraw.Draw(im)
        for j, it in enumerate(b["items"][s:s + per]):
            n = s + j + 1
            x, y = (j % COLS) * CELL, (j // COLS) * (CELL + LABEL)
            png = g / f"{key(it['id'])}.png"
            if png.exists():
                t = Image.open(png).convert("RGB")
                t.thumbnail((CELL - 8, CELL - 8))
                im.paste(t, (x + (CELL - t.width) // 2, y + (CELL - t.height) // 2))
                state = "rendered"
            else:
                why = failed.get(it["id"]) and "render failed" or nr.get(it["id"]) and "not visual" or "no render"
                d.rectangle([x + 4, y + 4, x + CELL - 4, y + CELL - 4], fill="#DDDDDD")
                d.text((x + 12, y + CELL // 2 - 8), why, font=FONT, fill="#555555")
                state = why
            d.rectangle([x, y, x + CELL - 1, y + CELL + LABEL - 1], outline="#999999")
            d.text((x + 6, y + CELL + 4), f"{n}. {it['name'][:30]}", font=FONT, fill="#000000")
            meta.append({"n": n, "id": it["id"], "sheet": s // per + 1, "state": state,
                         "how": (idx.get(it["id"]) or {}).get("how"), "reason": failed.get(it["id"]) or nr.get(it["id"])})
        im.save(out_dir / f"{batch_name}_s{s // per + 1}.png")
    (out_dir / f"{batch_name}_sheets.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    return meta


def main(argv):
    names = argv
    if argv[:1] == ["--kind"]:
        names = sorted(p.stem for p in (HERE / "work" / "batches").glob(f"{argv[1]}_[0-9]*.json"))
    for n in names:
        m = sheets(n)
        print(n, sum(x["state"] == "rendered" for x in m), "/", len(m), "rendered")


if __name__ == "__main__":
    main(sys.argv[1:])
