"""tools/ai/preset_gallery.py and effect_gallery.py offline: legacy colour-book decoding, the thumbnail backing, and
the patched effect descriptor's ASCII85 framing. Synthetic inputs only; no app (the Illustrator COM module is stubbed),
no network. Skipped without Pillow (the renderers need it)."""
import importlib, sys, tempfile, types, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT  # noqa: E402

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None


def load_gallery(name="preset_gallery"):
    sys.path.insert(0, str(ROOT / "tools" / "ai"))
    real = sys.modules.get("aicom")
    nop = lambda *a, **k: None  # noqa: E731
    sys.modules["aicom"] = types.SimpleNamespace(js_watch=lambda *a, **k: (None, None, []), ai_pid=nop, PANELS=(),
                                                 js=nop, main_hwnd=nop, dialogs=lambda: [], u32=None)
    try:
        return importlib.import_module(name)
    finally:
        if real is None:
            sys.modules.pop("aicom", None)
        else:
            sys.modules["aicom"] = real


ACBL = '''<?xml version="1.0" encoding="UTF-8"?>
<AdobeSwatchbook Version="0" BookID="1">
\t<Formats>
\t\t<Format ColorSpace="CMYK" Encoding="%s" Channels="4" ID="0"/>
\t\t</Formats>
\t<Swatches>
%s
\t\t</Swatches>
</AdobeSwatchbook>
'''


def acbl(path, enc, rows):
    sw = "\n".join(f'\t\t<Sp N="{i}"><C>{" ".join(str(v) for v in r)}</C></Sp>' for i, r in enumerate(rows))
    Path(path).write_text(ACBL % (enc, sw), encoding="utf-8")


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class LegacyColorBook(unittest.TestCase):
    def setUp(self):
        self.g = load_gallery()
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)

    def test_int8_book_reads_0_255_values(self):
        p = Path(self.t.name) / "int8.acbl"
        acbl(p, "Int8", [(0, 13, 153, 0), (0, 128, 255, 0), (0, 0, 0, 255)])
        got = self.g.swatch_colors(p)
        self.assertEqual(got[0], self.g.cmyk2rgb(0, 13 / 255, 153 / 255, 0))  # pale yellow, not flat yellow
        self.assertEqual(got[1], (255, 127, 0))
        self.assertEqual(got[2], (0, 0, 0))

    def test_int8_and_float_books_agree(self):
        a, b = Path(self.t.name) / "a.acbl", Path(self.t.name) / "b.acbl"
        acbl(a, "Int8", [(51, 102, 204, 0)])
        acbl(b, "Float", [(0.2, 0.4, 0.8, 0)])
        self.assertEqual(self.g.swatch_colors(a), self.g.swatch_colors(b))

    def test_unknown_encoding_fails_loudly(self):
        p = Path(self.t.name) / "x.acbl"
        acbl(p, "Int16", [(0, 0, 0, 0)])
        with self.assertRaises(ValueError):
            self.g.swatch_colors(p)


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class Backing(unittest.TestCase):
    """the composite must keep white paint and holes apart (on a white plate both vanished)."""

    def setUp(self):
        self.g = load_gallery()
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)

    def raw(self, draw):
        im = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        draw(ImageDraw.Draw(im))
        p = Path(self.t.name) / "raw.png"
        im.save(p)
        return p

    def assert_checker(self, px):
        self.assertIn(px[:3], (self.g.CHECK[0], self.g.CHECK[1]), px)

    def test_dark_art_with_white_lettering_and_a_hole(self):
        def draw(d):
            d.rectangle([0, 0, 399, 399], fill=(20, 20, 60, 255))   # dark plate: mean far below the old 225 rule
            d.rectangle([40, 40, 160, 120], fill=(255, 255, 255, 255))  # white lettering
            d.rectangle([240, 240, 340, 340], fill=(0, 0, 0, 0))     # a hole through the art
        out, _, bg = self.g.finish(self.raw(draw), white=True)
        self.assertIn("checker", bg)
        s = (self.g.SIZE - 28) / 400  # fit(): 14 px pad each side
        at = lambda x, y: out.getpixel((round(14 + x * s), round(14 + y * s)))
        self.assertEqual(at(100, 80), (255, 255, 255))   # white paint stays white
        self.assert_checker(at(290, 290))                # the hole shows the checker, not white
        self.assertLess(max(at(200, 30)), 70)            # dark paint stays dark

    def test_thin_antialiased_white_lines_count(self):
        def draw(d):
            d.rectangle([0, 0, 399, 150], fill=(30, 20, 120, 255))
            for y in range(170, 400, 12):  # thin white connectors at half alpha (antialiased 1 px lines)
                d.line([(0, y), (399, y)], fill=(255, 255, 255, 128))
        _, _, bg = self.g.finish(self.raw(draw), white=True)
        self.assertIn("checker", bg)

    def test_dark_art_without_white_stays_on_white(self):
        def draw(d):
            d.ellipse([0, 0, 399, 399], fill=(10, 10, 10, 255))
            d.ellipse([150, 150, 250, 250], fill=(0, 0, 0, 0))  # a hole, but no white paint to confuse it with
        out, _, bg = self.g.finish(self.raw(draw), white=True)
        self.assertEqual(bg, "white")
        self.assertEqual(out.getpixel((160, 160)), (255, 255, 255))

    def test_pale_art_still_gets_a_backing(self):
        def draw(d):
            d.rectangle([0, 0, 399, 399], fill=(225, 228, 220, 255))  # pale, but no channel reaches 230
        _, _, bg = self.g.finish(self.raw(draw), white=True)
        self.assertIn("checker", bg)

    def test_blank_render_raises(self):
        with self.assertRaises(ValueError):
            self.g.finish(self.raw(lambda d: None), white=True)


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class EffectDescriptor(unittest.TestCase):
    """a patched Photoshop-effect descriptor goes back into the .ai as %-prefixed ASCII85 lines ending in '~>'."""

    NL = "\r\n"
    BLOCK = NL.join(["/BasicFilter :", "(X) 1 0 /Filter ,", "/Dictionary : /NotRecorded ,", "/Binary : /ASCII85Decode ,",
                     '%!!!!"~>', "; (data) ,", "; /Dict ;"])

    def setUp(self):
        self.e = load_gallery("effect_gallery")

    def test_round_trip_at_every_line_length(self):
        for n in range(1, 140):  # covers encodings of 79 / 80 / 81 chars, where '~>' meets the 80-char line break
            b = bytes((i % 255) + 1 for i in range(n))
            blk = self.e.put_data(self.BLOCK, b)
            self.assertEqual(self.e.get_data(blk), b, n)
            body = blk.split("ASCII85Decode ," + self.NL)[1].split(self.NL + "; (data)")[0].split(self.NL)
            self.assertTrue(all(ln.startswith("%") for ln in body), n)
            self.assertTrue(body[-1].endswith("~>") and all("~" not in ln for ln in body[:-1]), n)


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class EffectRoute(unittest.TestCase):
    """applyEffect puts a Pathfinder effect after a group's fill/stroke stack (blank or unchanged frames); chain_first
    moves it to the head of the chain, where the Effect menu puts it. plate_of picks each effect's plate."""

    NL = "\r\n"
    STACK = NL.join(["/CompoundFilter :", "(Stack Style Filter) 0 0 /Filter ,", "1 /Visible ,", ";"])
    BLEND = NL.join(["/BasicFilter :", "(Blend Style Filter) 0 0 /Filter ,", "1 /Visible ,", ";"])

    def setUp(self):
        self.e = load_gallery("effect_gallery")

    def fx(self, name):
        return self.NL.join(["/BasicFilter :", f"({name}) 1 0 /Filter ,", "1 /Visible ,", "/Dictionary : /NotRecorded ,",
                             "3 /Int (Command) ,", "; /Dict ;"])

    def style(self, *parts):
        head = ["/KnownStyle :", "(Anon x) /Name ,", "/ActiveStyle :", "/CompoundFilter :",
                "(Chain Style Filter) 0 0 /Filter ,", "1 /Visible ,"]
        return self.NL.join(head) + self.NL + "".join(p + self.NL + " /Part ," + self.NL for p in parts) + ";" + self.NL

    def test_effect_after_the_stack_moves_to_the_head(self):
        pf = self.fx("Adobe Pathfinder")
        before = "%AI9_BeginArtStyles" + self.NL + self.style(self.STACK, pf, self.BLEND)
        after, n = self.e.chain_first(before, "Adobe Pathfinder")
        self.assertEqual(n, 1)
        self.assertEqual(after, "%AI9_BeginArtStyles" + self.NL + self.style(pf, self.STACK, self.BLEND))

    def test_already_first_and_other_effects_are_left_alone(self):
        pf, other = self.fx("Adobe Pathfinder"), self.fx("Adobe Drop Shadow")
        first = self.style(pf, self.STACK, self.BLEND)
        self.assertEqual(self.e.chain_first(first, "Adobe Pathfinder"), (first, 0))
        s = self.style(self.STACK, other, self.BLEND)
        self.assertEqual(self.e.chain_first(s, "Adobe Pathfinder"), (s, 0))

    def test_each_style_moves_within_its_own_chain(self):
        pf = self.fx("Adobe Pathfinder")
        two = self.style(self.STACK, self.BLEND) + self.style(self.STACK, pf, self.BLEND)
        self.assertEqual(self.e.chain_first(two, "Adobe Pathfinder"),
                         (self.style(self.STACK, self.BLEND) + self.style(pf, self.STACK, self.BLEND), 1))

    def test_plate_of(self):
        self.assertEqual(self.e.plate_of("Adobe Pathfinder"), "overlap")
        self.assertEqual(self.e.plate_of("PSAdapter_plugin_DrkS"), "photo")
        for le in ("Adobe PSL Gaussian Blur", "Adobe Drop Shadow", None):
            self.assertEqual(self.e.plate_of(le), "vector")
        self.assertEqual(len({ref for _, _, ref in self.e.PLATES.values()}), len(self.e.PLATES))  # a reference each

    def test_overlap_plate_shapes_overlap(self):
        import re
        svg = self.e.PLATES["overlap"][0].read_text("utf-8")
        x, y, w, h = (float(re.search(rf'<rect[^>]* {k}="([\d.]+)"', svg).group(1)) for k in ("x", "y", "width", "height"))
        cx, cy, r = (float(re.search(rf'<circle[^>]* {k}="([\d.]+)"', svg).group(1)) for k in ("cx", "cy", "r"))
        nx, ny = min(max(cx, x), x + w), min(max(cy, y), y + h)  # nearest point of the box to the circle centre
        self.assertLess((nx - cx) ** 2 + (ny - cy) ** 2, r * r)    # they share area
        self.assertFalse(x <= cx - r and cx + r <= x + w and y <= cy - r and cy + r <= y + h)  # and a boundary


if __name__ == "__main__":
    unittest.main()
