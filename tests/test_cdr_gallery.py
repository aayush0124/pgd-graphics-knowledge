"""tools/cdr/preset_gallery.py offline: bitmap-effect preset commands built from data-source values, the audit's
reason for pixel-identical renders, the .cmx DISP preview, the framed stroke mapping and --ids bookkeeping.
Synthetic inputs only; no CorelDRAW, no network. Skipped without Pillow (the renderer needs it)."""
import importlib.util, json, struct, sys, tempfile, unittest, unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


def load(name):
    """tools/cdr/<name>.py under its own module name (tools/ai has files of the same name)"""
    sys.path.insert(0, str(ROOT / "tools" / "cdr"))
    spec = importlib.util.spec_from_file_location("cdr_" + name, ROOT / "tools" / "cdr" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


DROPOFF = ('<container><itemData type="statusText" guid="d8" text="Gaussian"/><itemData type="statusText" guid="4a" '
           'text="Flat"/><itemData type="statusText" guid="36" text="Mesa"/></container>')


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class PresetCommand(unittest.TestCase):
    def setUp(self):
        self.g = load("preset_gallery")

    def test_values_become_explicit_keys_enum_as_list_index(self):
        vals = {"BevelWidth": 20.0, "Refraction": 70.0, "Dropoff": '<itemData type="statusText" guid="x" text="Mesa"/>',
                "Invert": 0, "Angle": 47.5}
        cmd, unsent = self.g.preset_command("GlassEffect", vals, {"Dropoff": DROPOFF})
        self.assertEqual(cmd, "GlassEffect BevelWidth=20,Refraction=70,Dropoff=2,Invert=0,Angle=47.5")
        self.assertEqual(unsent, {})

    def test_colour_items_are_left_out_and_reported(self):
        vals = {"FlareSize": 22.0, "FlareColorItem": '<itemData type="statusText" guid="1e" icon="c9"/>'}
        cmd, unsent = self.g.preset_command("LensFlareEffect", vals, {})
        self.assertEqual(cmd, "LensFlareEffect FlareSize=22")
        self.assertIn("colour", unsent["FlareColorItem"])

    def test_ui_paths_skipped_rename_applied_and_trailing_space_kept(self):
        vals = {"Preset": '<itemData guid="g" text="Rings"/>', "WhirlpoolPageSelected": 1, "RaysProperties": "x",
                "SmearLength": 9.0}
        cmd, _ = self.g.preset_command("WhirlpoolEffect", vals, {}, {"SmearLength": "Smear Length"})
        self.assertEqual(cmd, "WhirlpoolEffect Smear Length=9")
        cmd, _ = self.g.preset_command("WhirlpoolEffect", {"Preset": "x"}, {})
        self.assertEqual(cmd, "WhirlpoolEffect ")   # 'Effect' alone applies nothing; 'Effect ' applies

    def test_enum_item_missing_from_its_list_is_not_sent(self):
        cmd, unsent = self.g.preset_command("TheBossEffect", {"Dropoff": '<itemData guid="q" text="Odd"/>'},
                                            {"Dropoff": DROPOFF})
        self.assertEqual(cmd, "TheBossEffect ")
        self.assertIn("Dropoff", unsent)

    def test_same_render_reason(self):
        f = self.g.same_render_reason
        c = "LensFlareEffect FlareSize=84"
        r = f("Lens Flare Effect Preset", 2, [(c, {"FlareColorItem": "colour"})] * 3)
        self.assertIn("FlareColorItem cannot be sent", r)
        self.assertIsNone(f("The Boss Effect Preset", 1, [("TheBossEffect Width=20", {})] * 2))  # same values: keep
        r = f("Glass Effect Preset", 1, [("GlassEffect Opacity=50", {}), ("GlassEffect Opacity=70", {})])
        self.assertIn("ignored the keys", r)
        r = f("X", 1, [None, None])   # rows from an earlier run: no command known
        self.assertIn("ignored the keys", r)


class FakeSubPath:
    def __init__(self, owner, size):
        self.owner, self.SizeWidth, self.SizeHeight = owner, size, size

    def Delete(self):
        self.owner.items.remove(self)
        self.owner.deleted.append(self.SizeWidth)


class FakeSubPaths:
    def __init__(self, sizes):
        self.items = [FakeSubPath(self, z) for z in sizes]
        self.deleted = []

    @property
    def Count(self):
        return len(self.items)

    def Item(self, i):
        return self.items[i - 1]


class FakeCurve:
    """the bits of IVGCurve framed_map uses; the 'mapping' reverses the subpath order (as the real one may reorder)"""
    def __init__(self, sizes):
        self.SubPaths = FakeSubPaths(sizes)
        self.rects = []

    def GetCopy(self):
        return FakeCurve([p.SizeWidth for p in self.SubPaths.items])

    def AppendSubpathRectangle(self, left, top, right, bottom):
        self.rects.append((left, top, right, bottom))
        self.SubPaths.items.append(FakeSubPath(self.SubPaths, right - left))
        FakeCurve.last_copy = self

    def CreateCurveMappedToStroke(self, sp, scale, weld):
        return FakeCurve([p.SizeWidth for p in reversed(self.SubPaths.items)])


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class BrushParts(unittest.TestCase):
    def setUp(self):
        self.g = load("preset_gallery")
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)

    def test_framed_map_marks_the_brush_frame_then_drops_the_markers(self):
        part = FakeCurve([0.4, 2.0, 0.01])
        m = self.g.framed_map(part, (1.0, 2.0, 6.0, 0.5), "stroke")
        e = 1e-4
        self.assertEqual(FakeCurve.last_copy.rects, [(1.0, 2.0 + e, 1.0 + e, 2.0), (7.0, 2.5 + e, 7.0 + e, 2.5)])
        self.assertEqual(sorted(p.SizeWidth for p in m.SubPaths.items), [0.01, 0.4, 2.0])   # wherever they landed
        self.assertEqual(len(m.SubPaths.deleted), 2)
        self.assertEqual(part.SubPaths.Count, 3)   # the part's own curve is not touched

    def test_cmx_disp_reads_the_preview_dib(self):
        w, h = 4, 2
        stride = ((w * 24 + 31) // 32) * 4
        px = b"".join(bytes([0, 0, 255] * w) + b"\0" * (stride - 3 * w) for _ in range(h))   # BGR red, bottom-up
        dib = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(px), 0, 0, 0, 0) + px
        disp = b"\0\0\0\0" + dib
        riff = b"RIFF" + struct.pack("<I", 0) + b"CMX1" + b"cont" + struct.pack("<I", 3) + b"abc\0" + \
            b"DISP" + struct.pack("<I", len(disp)) + disp
        p = Path(self.t.name) / "b.cmx"
        p.write_bytes(riff)
        im = self.g.cmx_disp(p)
        self.assertEqual(im.size, (4, 2))
        self.assertEqual(im.convert("RGB").getpixel((0, 0)), (255, 0, 0))
        p.write_bytes(b"RIFF" + struct.pack("<I", 0) + b"CMX1")
        with self.assertRaises(ValueError):
            self.g.cmx_disp(p)

    def test_blank_means_fully_transparent(self):
        self.assertTrue(self.g.blank(Image.new("RGBA", (8, 8), (0, 0, 0, 0))))
        im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        im.putpixel((3, 3), (0, 0, 0, 255))
        self.assertFalse(self.g.blank(im))

    def test_keep_old_moves_frames_and_never_overwrites_a_kept_one(self):
        g = self.g
        out, pre = Path(self.t.name) / "out", Path(self.t.name) / "pre"
        out.mkdir()
        g.OUT = out
        st = type("St", (), {})()
        a, b = "Draw/x.cmx#a", "<LensFlareEffectDS.PresetItems>#b"
        st.index = {a: {"key": g.key(a)}}
        st.failed = {b: "old error"}
        (out / f"{g.key(a)}.png").write_bytes(b"new")
        pre.mkdir()
        g.keep_old(st, {a, b}, pre)
        self.assertEqual((pre / f"{g.key(a)}.png").read_bytes(), b"new")
        self.assertEqual((st.index, st.failed), ({}, {}))
        (out / f"{g.key(a)}.png").write_bytes(b"newer")
        st.index = {a: {}}
        g.keep_old(st, {a}, pre)
        self.assertEqual((pre / f"{g.key(a)}.png").read_bytes(), b"new")   # the first pre-fix frame is the one kept
        self.assertFalse((out / f"{g.key(a)}.png").exists())

    def test_read_ids_json_or_lines(self):
        p = Path(self.t.name) / "ids"
        p.write_text(json.dumps(["a", "b"]), encoding="utf-8")
        self.assertEqual(self.g.read_ids(p), ["a", "b"])
        p.write_text("a\n\n b \n", encoding="utf-8")
        self.assertEqual(self.g.read_ids(p), ["a", "b"])


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class EffectGalleryState(unittest.TestCase):
    def test_not_rendered_drops_the_old_frame(self):
        e = load("effect_gallery")
        with tempfile.TemporaryDirectory() as t:
            e.OUT, e.TMP = Path(t) / "out", Path(t) / "tmp"
            st = e.State()
            card = {"id": "e7220ca7-5cae-448a-a021-a80decc3ddba", "name": "Replace Colors"}
            png = e.OUT / f"{e.key(card['id'])}.png"
            png.write_bytes(b"old frame")
            st.index[card["id"]] = {"key": e.key(card["id"])}
            st.not_rendered(card, "status 'needs_input'")
            self.assertFalse(png.exists())
            self.assertEqual((card["id"] in st.index, st.nr[card["id"]]), (False, "status 'needs_input'"))

    def test_whirlpool_smear_length_goes_with_its_space(self):
        e = load("effect_gallery")
        self.assertEqual(e.KEY_ALIAS["WhirlpoolEffect"]["SmearLength"][0], "Smear Length")


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class EffectGalleryCrop(unittest.TestCase):
    """the 1:1 detail crop next to pixel-scale effects' frames, and the Bevel / Tune routes"""

    def setUp(self):
        self.e = load("effect_gallery")
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.e.OUT, self.e.TMP = Path(self.t.name) / "out", Path(self.t.name) / "tmp"

    def test_wants_crop_follows_the_harvest_path(self):
        w = self.e.wants_crop
        self.assertTrue(w({"path": "Effects/Sharpen/Adaptive Unsharp", "name": "Adaptive Unsharp"}))
        self.assertTrue(w({"path": "Effects/Blur/Directional Smooth"}))
        self.assertTrue(w({"path": "Effects/Camera/Diffuse", "name": "Diffuse"}))
        self.assertFalse(w({"path": "Effects/Camera/Lens Flare", "name": "Lens Flare"}))
        self.assertFalse(w({"path": "Effects/Blurry/x"}))
        self.assertFalse(w({}))

    def test_every_detail_item_is_a_bitmap_effect(self):
        items = json.loads((ROOT / "harvest" / "cdr" / "cdr_effect.json").read_text(encoding="utf-8"))["items"]
        detail = [it for it in items if self.e.wants_crop(it)]
        self.assertGreaterEqual(len(detail), 30)
        self.assertEqual([it["name"] for it in detail if not (it.get("extra") or {}).get("effect_id")], [])

    def test_crop_rect_is_page_inches_with_the_bottom_edge_as_y(self):
        e = self.e
        x, y, w, h = e.crop_rect((1408, 568, 512, 512))
        self.assertAlmostEqual(x, 1408 / 96)
        self.assertAlmostEqual(y, 0.0)              # the box reaches the page's bottom edge
        self.assertAlmostEqual((w, h), (512 / 96, 512 / 96))
        self.assertEqual(tuple(round(v, 6) for v in e.crop_rect((0, 0, 96, 48))), (0.0, 10.75, 1.0, 0.5))
        self.assertLessEqual(e.CROP_BOX[0] + e.CROP_BOX[2], 1920)
        self.assertLessEqual(e.CROP_BOX[1] + e.CROP_BOX[3], 1080)

    def test_crop_path(self):
        self.assertEqual(self.e.crop_path(Path("a") / "r00012.png"), Path("a") / "r00012_1to1.png")

    def test_put_moves_the_crop_records_it_and_drops_a_stale_one(self):
        e = self.e
        st = e.State()
        card = {"id": "a1ed2ae8-7da5-4a5f-b0f6-c60685b108d0", "name": "Adaptive Unsharp"}
        k = e.key(card["id"])
        (e.TMP / "r1.png").write_bytes(b"frame")
        (e.TMP / "r1_1to1.png").write_bytes(b"crop")
        st.put(card, e.TMP / "r1.png", {}, [], "how")
        self.assertEqual((e.OUT / f"{k}_1to1.png").read_bytes(), b"crop")
        self.assertEqual(st.index[card["id"]]["crop"], {"file": f"{k}_1to1.png", "box": list(e.CROP_BOX),
                                                        "scale": "1:1"})
        (e.TMP / "r2.png").write_bytes(b"frame 2")   # a render without a crop
        st.put(card, e.TMP / "r2.png", {}, [], "how")
        self.assertFalse((e.OUT / f"{k}_1to1.png").exists())
        self.assertNotIn("crop", st.index[card["id"]])
        (e.TMP / "r3.png").write_bytes(b"frame 3")
        (e.TMP / "r3_1to1.png").write_bytes(b"crop 3")
        st.put(card, e.TMP / "r3.png", {}, [], "how")
        st.fail(card, "boom")
        self.assertEqual([p.name for p in e.OUT.glob("*.png")], [])

    def test_routes_for_bevel_and_the_tune_effects(self):
        e = self.e
        cur = {"status": "current"}
        self.assertEqual(e.route(dict(cur, id="91062f47-0342-43a3-827b-ed78815cfce5"), {"invoke": {"cdr_guid": "x"}}),
                         ("custom", None))
        kind, why = e.route(dict(cur, id="c77b769b"), {"extra": {"effect_id": "TuneBlurEffect"}})
        self.assertEqual(kind, "fail")
        self.assertIn("Effect_%d", why)
        self.assertEqual(e.route(dict(cur, id="g"), {"extra": {"effect_id": "GaussianBlurEffect"}}), ("bitmap", None))
        name, spec = e.CUSTOM["91062f47-0342-43a3-827b-ed78815cfce5"]
        self.assertEqual((name, len(spec)), ("Bevel", 9))   # all nine IEffectBevel values, or the lights go black
        self.assertTrue(set(e.CUSTOM_READ) <= {k for k, _ in spec})

    def test_relative_file_values_resolve_against_pgd_home_absolute_ones_unchanged(self):
        e = self.e
        params = [{"key": "FileName", "name": "FileName", "type": "string"},
                  {"key": "Front", "name": "Front", "type": "int", "default": 0}]
        args, sent = e.com_args(None, params, {"FileName": "media/plate_photo.png", "Front": 5})
        self.assertEqual(args, [str(e.ROOT / "media" / "plate_photo.png"), 5])
        self.assertEqual(sent["FileName"], "media/plate_photo.png")      # the card's own value is what gets recorded
        absolute = str(Path(self.t.name) / "Vector Pattern 174.fill")
        self.assertEqual(e.com_args(None, params, {"FileName": absolute})[0][0], absolute)
        with unittest.mock.patch.dict("os.environ", {"PGD_HOME": self.t.name}):
            self.assertEqual(load("effect_gallery").pgd_path("media/x.png"), str(Path(self.t.name) / "media" / "x.png"))
        card = next(c for f in sorted((ROOT / "cards").glob("cdr_effect_*.json"))
                    for c in json.loads(f.read_text(encoding="utf-8"))["cards"] if c["id"] == "vector:Transparency:Bitmap")
        self.assertFalse(Path(card["demo_settings"]["FileName"]).is_absolute())

    def test_live_gallery_crops_exist_and_are_not_counted_as_frames(self):
        g = ROOT / "gallery" / "cdr_effect"
        if not (g / "index.json").exists():
            self.skipTest("no rendered gallery (untracked)")
        rows = json.loads((g / "index.json").read_text(encoding="utf-8"))
        for r in rows:
            if "crop" in r:
                self.assertEqual(Image.open(g / r["crop"]["file"]).size, tuple(r["crop"]["box"][2:]), r["name"])
        sys.path.insert(0, str(ROOT))
        import pipeline
        self.assertEqual(pipeline.gather(ROOT)["galleries"]["cdr_effect"]["frames"], len(rows))


if __name__ == "__main__":
    unittest.main()
