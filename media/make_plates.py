"""PGD test plates (what every gallery frame is rendered on).

    python media/make_plates.py

plate_photo.png  1920x1080: a soft photographic video frame (bring your own; not tracked) with a
                 crisp graphic strip along the bottom (8 saturated colour blocks, a grey ramp, white "PGD 2026" type
                 and hairlines), so a filter shows both its photographic and its hard-edge behaviour.
plate_vector.svg 1920x1080 vector art for Illustrator and CorelDRAW: orange rounded rectangle with a dark stroke, blue
                 star, yellow-to-magenta gradient circle, black "PGD" type and an open zigzag stroke (for path effects).
                 No background: shadows and glows land on the white artboard / page.
plate_overlap.svg 1920x1080 for Illustrator's Pathfinder effects: an orange rounded rectangle (back) and a blue circle
                 (front) that overlap, so Intersect / Minus Back / Subtract / Trap ... have shared area and a colour
                 boundary to act on (on plate_vector.svg no two filled shapes meet).
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
COLS = ["#E8202A", "#FF8A00", "#FFD400", "#22B04B", "#00A3E0", "#1E3FFF", "#7A2BD9", "#E0006E"]


def photo_plate():
    im = Image.open(HERE / "test_photo.png").convert("RGB").resize((1920, 1080))
    d = ImageDraw.Draw(im)
    y0 = 880
    d.rectangle([0, y0, 1920, 1080], fill="#101010")
    w = 1920 // 8
    for i, c in enumerate(COLS):
        d.rectangle([i * w, y0, (i + 1) * w - 1, y0 + 90], fill=c)
    for x in range(1920):  # grey ramp
        g = round(x / 1919 * 255)
        d.line([x, y0 + 90, x, y0 + 130], fill=(g, g, g))
    for k in range(6):     # hairlines 1..6 px
        d.line([1180, y0 + 150 + k * 8, 1900, y0 + 150 + k * 8], fill="#FFFFFF", width=k + 1)
    f = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 64)
    d.text((40, y0 + 135), "PGD 2026", font=f, fill="#FFFFFF")
    im.save(HERE / "plate_photo.png")


def star(cx, cy, r1, r2, n=5):
    import math
    pts = []
    for i in range(2 * n):
        r, a = (r1 if i % 2 == 0 else r2), math.pi * i / n - math.pi / 2
        pts.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    return " ".join(pts)


def vector_plate():
    zig = " ".join(f"{120 + i * 120},{960 + (40 if i % 2 else -40)}" for i in range(15))
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFD400"/>
<stop offset="1" stop-color="#E0006E"/></linearGradient></defs>
<g id="PGD_TEST">
<rect id="orange_box" x="160" y="200" width="520" height="560" rx="60" fill="#FF7A1A" stroke="#1A1A1A" stroke-width="6"/>
<polygon id="blue_star" points="{star(960, 470, 290, 120)}" fill="#1E5BFF"/>
<circle id="grad_circle" cx="1500" cy="470" r="270" fill="url(#g)"/>
<text id="pgd_type" x="960" y="900" font-family="Arial Black, Arial" font-weight="900" font-size="150" text-anchor="middle" fill="#111111">PGD</text>
<polyline id="zigzag" points="{zig}" fill="none" stroke="#1A1A1A" stroke-width="8"/>
</g></svg>
"""
    (HERE / "plate_vector.svg").write_text(svg, encoding="utf-8")


def overlap_plate():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
<g id="PGD_TEST">
<rect id="orange_box" x="420" y="220" width="640" height="560" rx="60" fill="#FF7A1A"/>
<circle id="blue_circle" cx="1140" cy="500" r="300" fill="#1E5BFF"/>
</g></svg>
"""
    (HERE / "plate_overlap.svg").write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    photo_plate()
    vector_plate()
    overlap_plate()
    print("plates written")
