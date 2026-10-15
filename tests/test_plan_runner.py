"""run_plan.py and the three app backends offline: every recipe plan compiles (each step gets a route, or says why it
is manual, or names the plan error), the plan hash, run results, the card-file writer and its lock, get / put / judge,
the frame compositing and strip, and the plan rules pgd.check_plan adds for runnable plans. No app, no network."""
import importlib, json, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, run  # noqa: E402

import pgd  # noqa: E402

try:
    from PIL import Image
    import numpy  # noqa: F401 (the PS effect gallery the PS backend reuses needs it)
except ImportError:  # pragma: no cover
    Image = None


def rp():
    import run_plan
    return importlib.reload(run_plan)


@unittest.skipIf(Image is None, "Pillow / numpy not installed (the backends reuse the galleries, which need them)")
class Compile(unittest.TestCase):
    def test_every_plan_compiles_with_a_route_or_a_reason(self):
        r = rp()
        n = 0
        for rec in r.recipes():
            for app, plan in rec["plans"].items():
                cs = r.compile_plan(rec, app)
                self.assertEqual(len(cs), len(plan["steps"]), (rec["id"], app))
                for c in cs:
                    n += 1
                    self.assertTrue(c["op"] or c.get("manual") or c.get("error"), (rec["id"], app, c))
                    self.assertFalse(c["op"] and (c.get("manual") or c.get("error")), (rec["id"], app, c))
                    json.dumps(c)  # compiled steps are plain data (run_plan.py show prints them)
        self.assertGreater(n, 500)

    def test_ps_routes(self):
        b = rp().backend("PS")
        cs = b.compile_steps({"steps": [
            {"kind": "ps_menu", "id": "1030"},                                    # Image Size: probe values
            {"kind": "ps_menu", "id": "1030", "script": "d.resizeImage(UnitValue(960, 'px'));"},
            {"kind": "ps_menu", "id": "2101"},                                    # File > Print: never run
            {"kind": "ps_menu", "id": "1942"},                                    # verified descriptor route
            {"kind": "ps_layer_style", "effects": [{"name": "Drop Shadow", "settings": {"distance": 4}},
                                                    {"name": "Drop Shadow", "settings": {"distance": 9}},
                                                    {"name": "Stroke", "settings": {"size": 3}}]},
            {"kind": "ps_api", "id": "class:Selection"}]}, {"plate": "photo"})
        self.assertIn("needs values", cs[0]["manual"])
        self.assertEqual(cs[1]["op"]["mode"], "script")
        self.assertIn("outside the document", cs[2]["manual"])
        self.assertTrue(cs[3]["op"]["src"].startswith('executeAction(tk("set")'))
        fx = cs[4]["op"]["fx"]
        self.assertEqual([f["multi"] for f in fx], ["dropShadowMulti", "dropShadowMulti", None])
        self.assertIn(["distance", "unit", "pixelsUnit", 9.0], fx[1]["spec"])
        self.assertIn("no scripted route", cs[5]["manual"])
        with self.assertRaises(ValueError):
            b.compile_steps({"steps": []}, {"plate": "vector"})

    def test_cdr_routes(self):
        b = rp().backend("CDR")
        cs = b.compile_steps({"steps": [
            {"kind": "cdr_effect", "id": "952e4cc8-4316-4bca-9ad9-9f79cf8574f2", "settings": {"Type": 0, "VPType": 0}},
            {"kind": "cdr_effect", "id": "952e4cc8-4316-4bca-9ad9-9f79cf8574f2",
             "settings": {"Type": 0, "VPType": 0, "VPX": 12.0, "VPY": 2.0}},
            {"kind": "cdr_menu", "id": "c44919b9-e389-4c0d-8a54-8e6e3fcfade3"},  # Convert to Bitmap: a dialog
            {"kind": "cdr_menu", "id": "68000526-6be1-4205-b2e9-6c9dff00f4c5"},  # Convert to Curves
            {"kind": "cdr_api", "id": "class:Shape", "script": "result = s"}]}, {"plate": "text"})
        self.assertIn("VPX, VPY", cs[0]["error"])
        self.assertEqual((cs[1]["op"]["mode"], cs[1]["op"]["meth"]), ("com", "CreateExtrude"))
        self.assertIn("opens a dialog", cs[2]["manual"])
        self.assertEqual(cs[3]["op"], {"mode": "menu", "guid": "68000526-6be1-4205-b2e9-6c9dff00f4c5"})
        self.assertEqual(cs[4]["op"]["mode"], "script")

    def test_ai_routes(self):
        b = rp().backend("AI")
        cs = b.compile_steps({"steps": [
            {"kind": "ai_menu", "id": "transformscale"},   # Scale...: a dialog
            {"kind": "ai_menu", "id": "group"},
            {"kind": "ai_blend_mode", "id": "MULTIPLY"},
            {"kind": "ai_api", "id": "class:PathItem"}]}, {"plate": "vector"})
        self.assertIn("opens a dialog", cs[0]["manual"])
        self.assertEqual(cs[1]["op"], {"mode": "menu", "cmd": "group"})
        self.assertEqual(cs[2]["op"], {"mode": "blend", "blend": "BlendModes.MULTIPLY"})
        self.assertIn("no scripted route", cs[3]["manual"])


class Records(unittest.TestCase):
    def test_plan_hash_ignores_the_records(self):
        r = rp()
        p = {"app": "PS", "steps": [{"kind": "ps_filter", "id": "gaussianBlur", "settings": {"radius": 3}}]}
        h = r.plan_hash(p)
        self.assertEqual(h, r.plan_hash(dict(p, run={"x": 1}, verified={"verdict": "pass"})))
        self.assertNotEqual(h, r.plan_hash(dict(p, input={"plate": "text"})))
        noted = dict(p, note="why", steps=[dict(p["steps"][0], note="a corrected note")])
        self.assertEqual(h, r.plan_hash(noted))  # prose fixed after a run keeps the run and its verdict
        self.assertNotEqual(h, r.plan_hash(dict(p, steps=[dict(p["steps"][0], settings={"radius": 4})])))

    def test_run_notes_carry_no_machine_paths(self):
        r = rp()
        home = str(r.HOME)
        self.assertEqual(r.public(f"ApplyBitmapPattern({home + chr(92)}media{chr(92)}plate_photo.png)"),
                         f"ApplyBitmapPattern(.{chr(92)}media{chr(92)}plate_photo.png)")
        self.assertEqual(r.public("a D:" + chr(92) + "tmp" + chr(92) + "x.png b"), "a <local path> b")
        self.assertEqual(r.public("16:9 at 10:30"), "16:9 at 10:30")

    def test_result_of(self):
        r = rp()
        res = lambda *s: r.result_of([{"status": x} for x in s])  # noqa: E731
        self.assertEqual((res("ok", "ok"), res("ok", "manual"), res("manual"), res("ok", "failed", "manual")),
                         ("complete", "partial", "manual", "failed"))

    def test_default_input(self):
        r = rp()
        self.assertEqual(r.default_input({"family": "text_effects"}, "PS"), {"plate": "text"})
        self.assertEqual(r.default_input({"family": "print_prep"}, "PS"), {"plate": "photo"})
        self.assertEqual(r.default_input({"family": "print_prep"}, "CDR"), {"plate": "vector"})
        self.assertEqual(r.default_input({"family": "photo_looks"}, "CDR"), {"plate": "photo"})


class CardWrites(unittest.TestCase):
    """update_plan / put / judge on a copy of one recipe file (PGD_HOME = a temp folder with cards + harvest links)"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "cards").mkdir()
        shutil.copy(ROOT / "cards" / "recipe_text_effects.json", self.tmp / "cards")
        shutil.copytree(ROOT / "harvest", self.tmp / "harvest")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self):
        return {"PGD_HOME": str(self.tmp)}

    def test_get_put_and_judge(self):
        g = run("run_plan.py", "get", "text_effects.neon_glow", "PS", env=self.env())
        self.assertEqual(g.returncode, 0, g.stderr)
        plan = json.loads(g.stdout)
        plan["input"] = {"plate": "text", "background": "#141414"}
        f = self.tmp / "p.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        p = run("run_plan.py", "put", "text_effects.neon_glow", "PS", f, env=self.env())
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = json.loads((self.tmp / "cards" / "recipe_text_effects.json").read_text(encoding="utf-8"))
        neon = next(c for c in doc["cards"] if c["id"] == "recipe:text_effects:neon_glow")
        self.assertEqual(neon["plans"]["PS"]["input"]["background"], "#141414")
        self.assertFalse((self.tmp / "work" / "plans" / "cards.lock").exists())
        j = run("run_plan.py", "judge", "text_effects.neon_glow", "PS", "--verdict", "pass", env=self.env())
        self.assertNotEqual(j.returncode, 0)  # no run of this version to judge
        self.assertIn("no current run", j.stdout + j.stderr)

    def test_put_refuses_a_plan_check_rejects(self):
        plan = {"app": "PS", "input": {"plate": "photo"},
                "steps": [{"kind": "ps_filter", "id": "gaussianBlur", "target": "nowhere"}]}
        f = self.tmp / "bad.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        before = (self.tmp / "cards" / "recipe_text_effects.json").read_text(encoding="utf-8")
        p = run("run_plan.py", "put", "text_effects.neon_glow", "PS", f, env=self.env())
        self.assertEqual(p.returncode, 1)
        self.assertIn("NOT SAVED", p.stdout)
        self.assertEqual(before, (self.tmp / "cards" / "recipe_text_effects.json").read_text(encoding="utf-8"))


class PlanRules(unittest.TestCase):
    def test_targets_must_be_labels(self):
        st = lambda **k: dict({"kind": "ps_filter", "id": "gaussianBlur", "settings": {"radius": 3}}, **k)  # noqa: E731
        ok = {"app": "PS", "input": {"plate": "photo", "text": "HI"},
              "steps": [dict(st(), **{"as": "blurred"}), st(target="blurred"), st(target="type")]}
        self.assertEqual(pgd.check_plan(ok), [])
        bad = {"app": "PS", "input": {"plate": "photo"}, "steps": [st(target="type layer")]}
        self.assertTrue(any("is not a label" in i for i in pgd.check_plan(bad)), pgd.check_plan(bad))
        self.assertTrue(any("plate" in i for i in pgd.check_plan({"app": "PS", "input": {"plate": "poster"}, "steps": []})))
        self.assertEqual(pgd.check_plan({"app": "PS", "steps": [st(target="anything")]}), [])  # no input: free text

    def test_shadow_hidden_under_an_outside_stroke(self):
        fx = lambda d, size=16, style="outsetFrame": {"app": "PS", "steps": [{"kind": "ps_layer_style", "effects": [  # noqa: E731
            {"name": "Stroke", "settings": {"style": style, "size": size}},
            {"name": "Drop Shadow", "settings": {"distance": d}}]}]}
        self.assertTrue(any("hidden under the stroke" in i for i in pgd.check_plan(fx(8))))
        self.assertEqual(pgd.check_plan(fx(24)), [])
        self.assertEqual(pgd.check_plan(fx(4, style="insetFrame")), [])           # an inside stroke covers nothing outside
        self.assertTrue(any("hidden" in i for i in pgd.check_plan(fx(6, size=16, style="centeredFrame"))))  # covers 8 px
        self.assertEqual(pgd.check_plan(fx(10, size=16, style="centeredFrame")), [])

    def test_empty_script_is_flagged(self):
        plan = {"app": "PS", "steps": [{"kind": "ps_api", "id": "class:Selection", "script": " "}]}
        self.assertTrue(any("script" in i for i in pgd.check_plan(plan)))

    def test_cdr_required_values(self):
        it = pgd._lookup("CDR", "cdr_effect", {"id": "952e4cc8-4316-4bca-9ad9-9f79cf8574f2"})
        self.assertEqual(pgd.missing_required(it, {"Type": 0, "VPType": 0}), ["VPX", "VPY"])
        self.assertEqual(pgd.missing_required(it, {"Type": 0, "VPType": 0, "VPX": 1, "VPY": 2}), [])


@unittest.skipIf(Image is None, "Pillow not installed")
class Frames(unittest.TestCase):
    def test_transparency_over_the_checker_and_the_strip(self):
        r = rp()
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            im.paste((255, 255, 255, 255), (16, 16, 48, 48))
            im.save(t / "a.png")
            o = r.opaque(t / "a.png")
            self.assertEqual(o.mode, "RGB")
            self.assertEqual(o.getpixel((20, 20)), (255, 255, 255))   # white paint stays white
            self.assertIn(o.getpixel((2, 2)), ((140, 140, 140), (115, 115, 115)))  # transparency -> grey checker
            r.strip([t / "a.png", None, t / "a.png", t / "a.png", t / "a.png"], t / "s.png", ["in", "1", "2", "3", "4"])
            with Image.open(t / "s.png") as s:
                self.assertEqual(s.size, (4 * 320, 2 * (180 + 22)))


@unittest.skipIf(Image is None, "Pillow / numpy not installed")
class Damage(unittest.TestCase):
    """the damaged photo input: reproducible, cached, and each kind of damage really changes the picture"""

    def test_damage_is_reproducible_and_visible(self):
        r = rp()
        from PIL import ImageChops, ImageStat
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "media").mkdir()
            plate = Image.new("RGB", (192, 108), (120, 90, 60))
            for x in range(0, 192, 12):  # stripes: tilt and blur change nothing on a flat colour
                plate.paste((230, 220, 200), (x, 0, x + 4, 108))
            plate.save(t / "media" / "plate_photo.png")
            r.HOME = t
            clean = Image.open(t / "media" / "plate_photo.png").convert("RGB")
            for dmg in ({"noise": 12}, {"dust": 40}, {"jpeg": 5, "haze": 0.3}, {"tilt": 3, "blur": 1.5}):
                a = r.damaged_photo(dmg)
                with Image.open(a) as im:
                    b = im.convert("RGB")
                self.assertEqual(b.size, clean.size, dmg)
                self.assertGreater(sum(ImageStat.Stat(ImageChops.difference(b, clean)).mean), 0.05, dmg)
                self.assertEqual(r.damaged_photo(dmg), a)  # same settings -> the same cached file
            self.assertNotEqual(r.damaged_photo({"noise": 12}), r.damaged_photo({"noise": 13}))

    def test_check_plan_rules(self):
        ok = {"app": "CDR", "input": {"plate": "photo", "damage": {"noise": 12, "tilt": -2}}, "steps": []}
        self.assertEqual(pgd.check_plan(ok), [])
        self.assertTrue(pgd.check_plan({"app": "CDR", "input": {"plate": "vector", "damage": {"noise": 1}}, "steps": []}))
        self.assertTrue(pgd.check_plan({"app": "CDR", "input": {"plate": "photo", "damage": {"fog": 1}}, "steps": []}))


if __name__ == "__main__":
    unittest.main()
