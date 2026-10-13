"""tools/ps/effect_gallery.py offline: demo values typed into Action Manager specs, the read-back reconcile and its
stale-descriptor re-check, plates per kind, the blend plate's top layer, the 960x540 frame + 1:1 crop, the crop rule,
dialog field pairing, and the index / failed / not_rendered bookkeeping. Synthetic inputs (plus the harvest and cards);
no Photoshop, no network. Skipped without Pillow / numpy (the renderer needs them)."""
import hashlib, importlib.util, json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT  # noqa: E402

try:
    from PIL import Image
    import numpy
except ImportError:  # pragma: no cover
    Image = None


def load():
    """tools/ps/effect_gallery.py under its own module name (tools/ai and tools/cdr have files of the same name)"""
    spec = importlib.util.spec_from_file_location("ps_effect_gallery", ROOT / "tools" / "ps" / "effect_gallery.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@unittest.skipIf(Image is None, "Pillow / numpy not installed (the gallery renderer needs them)")
class Specs(unittest.TestCase):
    def setUp(self):
        self.e = load()

    ITEM = {"params": [{"name": "Brush Type", "key": "brushType", "type": "enum", "extra": {"enum_type": "brushType"},
                        "enum": [{"value": "brushWideSharp", "label": "Wide Sharp"}]},
                       {"name": "Color", "key": "color", "type": "color"},
                       {"name": "Radius", "key": "radius", "type": "number", "unit": "px"},
                       {"name": "Flare Center", "key": "flareCenter", "type": "point", "extra": {"class": "paint"}}]}

    def test_demo_values_typed_by_name_or_key(self):
        c = {"id": "x", "demo_settings": {"Brush Type": "Wide Sharp", "Color": "#00E5FF", "radius": 18,
                                          "Flare Center": [0.6, 0.15], "nope": 1}}
        spec, by, bad = self.e.spec_for("ps_blend_mode", c, self.ITEM)
        self.assertEqual(by["Brush Type"], ["brushType", "enum", "brushType", "brushWideSharp"])
        self.assertEqual(by["Color"], ["color", "rgb", 0.0, 229.0, 255.0])
        self.assertEqual(by["radius"], ["radius", "unit", "pixelsUnit", 18.0])
        self.assertEqual(by["Flare Center"], ["flareCenter", "point", "paint", 0.6, 0.15])
        self.assertEqual(bad, [("nope", "no harvested param of this name or key")])
        self.assertEqual(len(spec), 4)

    def test_reconcile_reports_changed_and_dropped(self):
        c = {"id": "x", "demo_settings": {"Color": "#00E5FF", "radius": 18, "Flare Center": [0.6, 0.15]}}
        _, by, bad = self.e.spec_for("ps_blend_mode", c, self.ITEM)
        rgb = {"t": "OBJECTTYPE", "cls": "RGBColor", "v": {"red": {"t": "DOUBLETYPE", "v": 0},
               "grain": {"t": "DOUBLETYPE", "v": 229}, "blue": {"t": "DOUBLETYPE", "v": 255}}}
        rb = {"radius": {"t": "UNITDOUBLE", "v": 10, "unit": "pixelsUnit"}, "color": rgb}
        ap, dr, ch, had = self.e.reconcile(by, bad, rb)
        self.assertEqual((ap["Color"], ap["radius"], ch, dr, had), ("#00E5FF", 10, {"radius": [18.0, 10]}, ["Flare Center"], True))
        ap, _, ch, had = self.e.reconcile(by, [], {})
        self.assertEqual((ap["radius"], ch, had), (18.0, {}, False))  # empty descriptor: the values sent

    def test_respec_swaps_in_the_read_back_values_only(self):
        spec = [["amount", "unit", "percentUnit", 250.0], ["radius", "unit", "pixelsUnit", 4.0], ["threshold", "int", 0],
                ["mode", "enum", "blurMethod", "zoom"]]
        by = {"Amount": spec[0], "Radius": spec[1], "Threshold": spec[2], "Method": spec[3]}
        out = self.e.respec(spec, by, {"Amount": [250.0, 50], "Method": ["zoom", "spin"]})
        self.assertEqual(out, [["amount", "unit", "percentUnit", 50], ["radius", "unit", "pixelsUnit", 4.0],
                               ["threshold", "int", 0], ["mode", "enum", "blurMethod", "spin"]])
        self.assertEqual(spec[0][3], 250.0)  # the original spec is left alone

    def test_list_and_object_values(self):
        e, a = self.e, self.e.harvest("ps_adjustment")
        lv = {"shadowLevels": [-40, 0, 40]}
        for cid in ("colorBalance", "adjustmentLayer:colorBalance"):  # declared "/integer /list" / read-back list of ints
            by = e.spec_for("ps_adjustment", {"demo_settings": lv}, a[cid])[1]
            self.assertEqual(by["shadowLevels"], ["shadowLevels", "list", [["int", -40], ["int", 0], ["int", 40]]], cid)
        # destructive Channel Mixer: only the class is declared; members typed from the adjustment layer's read-back
        by = e.spec_for("ps_adjustment", {"demo_settings": {"gray": {"red": 40, "grain": 60}}}, a["channelMixer"])[1]
        self.assertEqual(by["gray"], ["gray", "obj", "channelMatrix", [["red", "unit", "percentUnit", 40.0],
                                                                       ["grain", "unit", "percentUnit", 60.0]]])
        # Curves / Levels / Selective Color: lists of objects typed from the class's declared members
        curve = {"adjustment": [{"channel": "composite", "curve": [[0, 0], [64, 40]]}]}
        by = e.spec_for("ps_adjustment", {"demo_settings": curve}, a["curves"])[1]
        self.assertEqual(by["adjustment"], ["adjustment", "list", [["obj", "curvesAdjustment", [
            ["channel", "chref", "composite"], ["curve", "list", [["point", "paint", 0.0, 0.0], ["point", "paint", 64.0, 40.0]]]]]]])
        lev = {"Adjustment": [{"channel": "composite", "input": [30, 220], "gamma": 1}]}
        by = e.spec_for("ps_adjustment", {"demo_settings": lev}, a["adjustmentLayer:levels"])[1]
        self.assertEqual(by["Adjustment"][2][0][2], [["channel", "chref", "composite"], ["input", "list", [["int", 30], ["int", 220]]],
                                                    ["gamma", "dbl", 1.0]])  # floatType: a double even when written as 1
        sc = {"Color Correction": [{"colors": "reds", "cyan": 50}]}
        by = e.spec_for("ps_adjustment", {"demo_settings": sc}, a["selectiveColor"])[1]
        self.assertEqual(by["Color Correction"][2][0][2], [["colors", "enum", "colors", "reds"], ["cyan", "int", 50]])
        self.assertEqual(e.sent_plain(by["Color Correction"]), sc["Color Correction"])
        self.assertEqual(e.fmt(e.spec_for("ps_adjustment", {"demo_settings": lv}, a["colorBalance"])[1]["shadowLevels"]),
                         "shadowLevels: [-40, 0, 40]")
        bad = e.spec_for("ps_adjustment", {"demo_settings": {"shadowLevels": 5}}, a["colorBalance"])[2]
        self.assertEqual(bad, [("shadowLevels", "expects a list, got 5")])

    def test_js_builder_encodes_every_kind_the_specs_use(self):
        e, used = self.e, set()

        def walk(s):  # s = [kind, ...] without the key
            used.add(s[0])
            if s[0] == "list":
                for x in s[1]:
                    walk(x)
            elif s[0] == "obj":
                for m in s[2]:
                    walk(m[1:])
        for kind in e.KINDS:
            items = e.harvest(kind)
            for c in e.cards(kind):
                for sp in e.spec_for(kind, c, items[c["id"]])[0]:
                    walk(sp[1:])
        self.assertTrue({"list", "obj", "chref", "point", "enum", "int"} <= used, used)
        for k in used:
            self.assertIn(f't == "{k}"', e.PSJ, k)

    def test_key_is_sha1_prefix(self):
        self.assertEqual(self.e.key("gaussianBlur"), hashlib.sha1(b"gaussianBlur").hexdigest()[:12])


@unittest.skipIf(Image is None, "Pillow / numpy not installed (the gallery renderer needs them)")
class Plates(unittest.TestCase):
    def setUp(self):
        self.e = load()
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.d = Path(self.t.name)

    def test_every_kind_has_a_described_plate(self):
        e = self.e
        self.assertEqual(set(e.SETUP), set(e.KINDS))
        self.assertEqual(e.SETUP["ps_filter"], "photo")
        self.assertEqual(e.SETUP["ps_adjustment"], "photo")
        self.assertEqual(e.SETUP["ps_layer_style"], "text")
        self.assertEqual(e.SETUP["ps_blend_mode"], "blend")
        self.assertTrue(set(e.SETUP.values()) <= set(e.PLATES))

    def test_blend_top_layer_bands(self):
        with Image.open(self.e.blend_top(self.d / "top.png")) as f:
            im = f.copy()
        self.assertEqual((im.size, im.mode), ((1920, 1080), "RGBA"))
        px = im.load()
        for i, c in enumerate(self.e.BARS):  # band 1: eight opaque colour bars
            self.assertEqual(px[i * 240 + 120, 180], c + (255,))
        ramp = [px[x, 540] for x in range(0, 1920, 64)]  # band 2: opaque grey ramp, black to white
        self.assertEqual((ramp[0], px[1919, 540]), ((0, 0, 0, 255), (255, 255, 255, 255)))
        self.assertTrue(all(a[0] <= b[0] and a[0] == a[1] == a[2] and a[3] == 255 for a, b in zip(ramp, ramp[1:])))
        self.assertEqual(px[0, 900], (255, 0, 200, 255))  # band 3: magenta -> cyan fading out
        self.assertEqual(px[1919, 900], (0, 229, 255, 0))
        self.assertEqual(px[960, 900][3], 255 - round(255 * 960 / 1919))

    def test_derive_makes_the_frame_and_the_exact_1to1_crop(self):
        e = self.e
        a = numpy.random.default_rng(7).integers(0, 256, (1080, 1920, 3), dtype=numpy.uint8)
        Image.fromarray(a).save(self.d / "full.png")
        e.derive(self.d / "full.png", self.d / "f.png", self.d / "f_1to1.png")
        with Image.open(self.d / "f.png") as f, Image.open(self.d / "f_1to1.png") as c:
            self.assertEqual(f.size, e.FRAME)
            x, y, w, h = e.CROP_BOX
            self.assertTrue((numpy.asarray(c) == a[y:y + h, x:x + w]).all())
        self.assertLessEqual((x + w, y + h), (1920, 1080))
        e.derive(self.d / "full.png", self.d / "g.png")
        self.assertFalse((self.d / "g_1to1.png").exists())

    def test_diff_stats(self):
        a = numpy.zeros((4, 4, 3), dtype=numpy.uint8)
        b = a.copy()
        b[0, 0] = (10, 0, 0)
        Image.fromarray(a).save(self.d / "a.png")
        Image.fromarray(b).save(self.d / "b.png")
        self.assertEqual(self.e.diff_stats(self.d / "a.png", self.d / "a.png"), {"mean": 0.0, "max": 0, "over2": 0.0})
        self.assertEqual(self.e.diff_stats(self.d / "a.png", self.d / "b.png"), {"mean": 0.208, "max": 10, "over2": 0.0625})
        self.assertIsNone(self.e.diff_stats(self.d / "a.png", self.d / "missing.png"))


@unittest.skipIf(Image is None, "Pillow / numpy not installed (the gallery renderer needs them)")
class CropRule(unittest.TestCase):
    def setUp(self):
        self.e = load()
        self.items = {k: self.e.harvest(k) for k in self.e.KINDS}

    def test_pixel_scale_filters_get_a_crop(self):
        w = lambda i: self.e.wants_crop(self.items["ps_filter"][i])  # noqa: E731
        for i in ("gaussianBlur", "unsharpMask", "smartSharpen", "addNoise", "dustAndScratches", "median", "highPass",
                  "findEdges", "maximum", "minimum", "despeckle", "sharpen"):
            self.assertTrue(w(i), i)
        for i in ("twirl", "lensFlare", "cutout", "offset", "polar"):
            self.assertFalse(w(i), i)
        self.assertTrue(self.e.wants_crop(self.items["ps_adjustment"]["adjustmentLayer:grainAdjustment"]))
        self.assertFalse(self.e.wants_crop(self.items["ps_adjustment"]["curves"]))

    def test_detail_ids_exist_in_the_harvest(self):
        ids = set(self.items["ps_filter"]) | set(self.items["ps_adjustment"])
        self.assertEqual(self.e.DETAIL_IDS - ids, set())


@unittest.skipIf(Image is None, "Pillow / numpy not installed (the gallery renderer needs them)")
class Jobs(unittest.TestCase):
    def setUp(self):
        self.e = load()

    def test_every_renderable_card_gets_a_job_or_a_reason(self):
        e = self.e
        for kind in e.KINDS:
            items = e.harvest(kind)
            for c in e.cards(kind):
                if e.not_rendered_reason(c):
                    continue
                try:
                    j, by, bad, how = e.job_for(kind, c, items[c["id"]], "x.png")
                except ValueError as ex:
                    self.assertIn("no Action Manager event", str(ex))
                    continue
                self.assertEqual(j["setup"], e.SETUP[kind])
                self.assertIn(j["mode"], ("event", "adjlayer", "style", "blend"))
                self.assertEqual(bad, [], (kind, c["id"]))

    def test_routes_per_kind(self):
        e = self.e
        f, a, s, b = (e.harvest(k) for k in e.KINDS)
        j = e.job_for("ps_blend_mode", {"id": "multiply"}, b["multiply"], "x.png")[0]
        self.assertEqual((j["mode"], j["ev"], j["setup"]), ("blend", "multiply", "blend"))
        j = e.job_for("ps_layer_style", {"id": "dropShadow", "demo_settings": {}}, s["dropShadow"], "x.png")[0]
        self.assertEqual((j["mode"], j["key"], j["cls"], j["setup"]), ("style", "dropShadow", "dropShadow", "text"))
        j = e.job_for("ps_adjustment", {"id": "x", "demo_settings": {}}, a["adjustmentLayer:invert"], "x.png")[0]
        self.assertEqual((j["mode"], j["cls"]), ("adjlayer", "invert"))
        j, _, _, how = e.job_for("ps_filter", {"id": "x", "demo_settings": {"radius": 18}}, f["gaussianBlur"], "x.png")
        self.assertEqual((j["mode"], j["ev"], j["spec"]), ("event", "gaussianBlur", [["radius", "unit", "pixelsUnit", 18.0]]))
        self.assertIn("DialogModes.NO", how)

    def test_not_rendered_reasons(self):
        r = self.e.not_rendered_reason
        self.assertIsNone(r({"status": "current", "scriptable": "partial"}))
        self.assertIn("needs_input", r({"status": "needs_input", "scriptable": "yes"}))
        self.assertIn("scriptable is 'no'", r({"status": "current", "scriptable": "no", "scripting": "UI only"}))

    def test_control_set_is_a_gallery_filter_a_dialog_filter_and_an_adjustment(self):
        e = self.e
        f = e.harvest("ps_filter")
        (k1, i1), (k2, i2), (k3, i3) = e.CONTROL
        self.assertTrue(f[i1]["extra"].get("filter_gallery"))
        self.assertFalse(f[i2]["extra"].get("filter_gallery"))
        self.assertEqual((k1, k2, k3), ("ps_filter", "ps_filter", "ps_adjustment"))
        self.assertIn(i3, e.harvest("ps_adjustment"))


@unittest.skipIf(Image is None, "Pillow / numpy not installed (the gallery renderer needs them)")
class Bookkeeping(unittest.TestCase):
    def setUp(self):
        self.e = load()
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.e.GAL = Path(self.t.name)

    def test_one_list_per_id_and_frames_follow_the_index(self):
        e = self.e
        st = e.State("ps_filter")
        k = e.key("gaussianBlur")
        (st.dir / f"{k}.png").write_bytes(b"frame")
        (st.dir / f"{k}_1to1.png").write_bytes(b"crop")
        st.put("gaussianBlur", st.index, {"key": k, "id": "gaussianBlur", "crop": {"file": f"{k}_1to1.png"}})
        self.assertTrue((st.dir / f"{k}_1to1.png").exists())
        st.put("gaussianBlur", st.index, {"key": k, "id": "gaussianBlur"})  # re-rendered without a crop
        self.assertFalse((st.dir / f"{k}_1to1.png").exists())
        st.put("gaussianBlur", st.failed, "boom")
        self.assertEqual((list(st.index), st.failed), ([], {"gaussianBlur": "boom"}))
        self.assertFalse((st.dir / f"{k}.png").exists())
        st.put("gaussianBlur", st.notr, "not current")
        st.save()
        self.assertEqual(json.loads((st.dir / "failed.json").read_text(encoding="utf-8")), {})
        self.assertEqual(json.loads((st.dir / "not_rendered.json").read_text(encoding="utf-8")), {"gaussianBlur": "not current"})
        self.assertEqual(e.State("ps_filter").notr, {"gaussianBlur": "not current"})  # resumes from the saved files

    def test_pair_fields_labels_edits_by_row(self):
        ctrls = [{"cls": "Static", "x": 707, "y": 414, "text": "&Amount:"}, {"cls": "Edit", "x": 773, "y": 414, "text": "250"},
                 {"cls": "Static", "x": 831, "y": 414, "text": "%"}, {"cls": "Edit", "x": 773, "y": 467, "text": "4.0"},
                 {"cls": "Static", "x": 713, "y": 467, "text": "&Radius:"}, {"cls": "Edit", "x": 1605, "y": 154, "text": "6"}]
        self.assertEqual(self.e.pair_fields(ctrls), [{"label": "", "value": "6"}, {"label": "Amount", "value": "250"},
                                                     {"label": "Radius", "value": "4.0"}])


@unittest.skipIf(Image is None, "Pillow / numpy not installed (the gallery renderer needs them)")
class LiveGallery(unittest.TestCase):
    """the rendered galleries (untracked): every card in exactly one list, frame and crop sizes, plate recorded"""

    def test_galleries_are_consistent(self):
        e = load()
        if not (ROOT / "gallery" / "ps_filter" / "index.json").exists():
            self.skipTest("no rendered Photoshop effect gallery (untracked)")
        for kind in e.KINDS:
            g = ROOT / "gallery" / kind
            idx = {r["id"]: r for r in json.loads((g / "index.json").read_text(encoding="utf-8"))}
            failed = json.loads((g / "failed.json").read_text(encoding="utf-8"))
            notr = json.loads((g / "not_rendered.json").read_text(encoding="utf-8"))
            ids = [c["id"] for c in e.cards(kind)]
            for i in ids:
                self.assertEqual((i in idx) + (i in failed) + (i in notr), 1, (kind, i))
            for r in idx.values():
                self.assertEqual(r["plate"], e.SETUP[kind])
                with Image.open(g / f"{r['key']}.png") as f:
                    self.assertEqual(f.size, e.FRAME, r["id"])
                if "crop" in r:
                    with Image.open(g / r["crop"]["file"]) as f:
                        self.assertEqual(f.size, tuple(r["crop"]["box"][2:]), r["id"])
            frames = {p.stem for p in g.glob("*.png") if not p.name.startswith("ref") and not p.stem.endswith("_1to1")}
            self.assertEqual(frames, {r["key"] for r in idx.values()}, kind)


if __name__ == "__main__":
    unittest.main()
