"""Regression tests for the 2026-10-20 stress review: each pins one confirmed defect (the plan pre-flight's closed
schema and value rules, search and card ranking, the CLIs' argument handling and exit codes, the plan runner's card
writes, the skeleton stage, the docs stage, the CorelDRAW command form, the preset parsers). Offline: no app, no
network, no LLM; the ones that load a renderer skip without Pillow."""
import importlib, importlib.util, json, math, os, shutil, sys, tempfile, unittest, zipfile, zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, run  # noqa: E402

import pgd, validate_cards  # noqa: E402

try:
    import PIL  # noqa: F401
    import numpy  # noqa: F401
    DEPS = True
except ImportError:  # pragma: no cover
    DEPS = False

NAN, INF = float("nan"), float("inf")
GB = {"kind": "ps_filter", "id": "gaussianBlur"}
LS = lambda *fx, **kw: dict({"kind": "ps_layer_style", "effects": list(fx)}, **kw)  # noqa: E731
STROKE = lambda **s: {"name": "Stroke", "settings": dict({"style": "insetFrame", "size": 16}, **s)}  # noqa: E731
SHADOW = lambda **s: {"name": "Drop Shadow", "settings": dict({"distance": 30}, **s)}  # noqa: E731


def rp():
    import run_plan
    return importlib.reload(run_plan)


def load_tool(app, name):
    spec = importlib.util.spec_from_file_location(f"stress_{app}_{name}", ROOT / "tools" / app / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def plan(*steps, app="PS", **kw):
    return dict({"app": app, "steps": list(steps)}, **kw)


def flags(p):
    return pgd.check_plan(p)


class Deps(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("PGD_REQUIRE_DEPS") == "1", "PGD_REQUIRE_DEPS=1 (CI) only")
    def test_render_test_dependencies_are_installed(self):
        """CI installs Pillow and numpy: without them 70+ gallery / plan-runner tests skip and CI stays green"""
        self.assertTrue(DEPS, "Pillow / numpy missing: the gallery and plan-runner tests would only skip")


class PlanSchema(unittest.TestCase):
    """check_plan is a closed schema that never raises (findings: open schema, crashes on wrong shapes)"""

    def test_misspelt_keys_and_missing_steps_are_issues(self):
        for p in ({"app": "PS", "Steps": [GB]}, {"app": "PS", "step": [GB]}, {},
                  plan(dict(GB, setting={"radius": 40})), plan(dict(GB, Settings={"radius": 40})),
                  plan(dict(GB, traget="photo")), plan(GB, inputs={"plate": "vector"}),
                  plan(LS(STROKE(), name="Stroke", settings={"size": 99999})), plan(LS(STROKE(), bogus=1))):
            self.assertTrue(flags(p), p)
        self.assertEqual(flags({"app": "CDR", "input": {"plate": "photo"}, "steps": []}), [])  # input rules alone

    def test_wrong_shapes_come_back_as_issues(self):
        for p in ([GB], None, "plan", plan(*[]) | {"steps": {"a": 1}}, plan("Gaussian Blur"), plan(None),
                  plan(dict(GB, id=["gaussianBlur"])), plan(dict(GB, name=5)), plan(dict(GB, settings=[1, 2])),
                  plan(LS("Stroke")), plan(GB, input="photo"), plan(dict(GB, labels=5)),
                  plan(dict(GB, labels="ab")), {"cards": [{"id": "x"}]}):
            out = pgd.check_plan(p)  # never raises
            self.assertTrue(out, p)

    def test_non_finite_and_string_values(self):
        self.assertTrue(flags(plan(dict(GB, settings={"radius": NAN}))))
        self.assertTrue(flags(plan({"app": "AI", "kind": "ai_effect", "id": "Live Rasterize Effect Setting",
                                    "settings": {"padding": INF}}, app="AI")))
        ext = {"kind": "ai_effect", "id": "Live Adobe Geometry3D Extrude"}
        self.assertTrue(flags(plan(dict(ext, settings={"Geometry3DkSunlightNameKey": {"x": 1}}), app="AI")))
        self.assertTrue(flags(plan(dict(ext, settings={"Geometry3DkShadowProfileKey": NAN}), app="AI")))
        self.assertTrue(flags(plan(GB, input={"plate": "photo", "damage": {"tilt": NAN, "noise": INF}})))
        p = {"name": "x", "type": "string"}
        self.assertIsNone(validate_cards.check_value("x", p, "fine"))
        self.assertIn("expects a string", validate_cards.check_value("x", p, 42))
        lv = {"name": "s", "type": "object", "extra": {"value": [{"t": "INTEGERTYPE", "v": 0}] * 3}}
        self.assertIn("not finite", validate_cards.check_value("s", lv, [0, NAN, 0]))
        il = {"name": "m", "type": "object", "extra": {"declared_type": "/integer /list"}}
        self.assertIn("not finite", validate_cards.check_value("m", il, [1, INF]))

    def test_object_members_against_their_declared_types(self):
        curves = lambda **o: plan({"kind": "ps_adjustment", "id": "curves", "settings": {  # noqa: E731
            "adjustment": [dict({"channel": "composite", "curve": [[0, 0], [255, 255]]}, **o)]}})
        self.assertEqual(flags(curves()), [])
        for bad in ({"curve": "S"}, {"curve": [[0, 0, 0], [255, 255, 255]]}, {"channel": 5}, {"auto": "yes"}):
            self.assertTrue(flags(curves(**bad)), bad)
        self.assertTrue(flags(plan({"kind": "ps_adjustment", "id": "levels", "settings": {
            "adjustment": [{"channel": "composite", "input": "0-255"}]}})))
        self.assertTrue(flags(plan({"kind": "ps_adjustment", "id": "channelMixer", "settings": {"red": {"red": "lots"}}})))
        self.assertTrue(flags(plan({"kind": "ps_adjustment", "id": "colorBalance",
                                    "settings": {"shadowLevels": ["a", "b", "c"]}})))

    def test_input_fields_are_checked(self):
        for inp in ({"plate": "text", "at": "middle"}, {"plate": "text", "color": "red"}, {"plate": "text", "size": -5},
                    {"plate": "text", "colour": "#FFFFFF"}, {"plate": "photo", "damage": {"haze": 5}},
                    {"plate": "photo", "damage": {"dust": 1e12}}, {"plate": "photo", "damage": {"jpeg": 1000}}):
            self.assertTrue(flags(plan(input=inp)), inp)
        self.assertEqual(flags(plan(input={"plate": "text", "text": "HI", "at": [960, 540], "size": 150,
                                           "color": "#FFFFFF", "background": "#141414", "font": "Arial"})), [])

    def test_input_needs_a_plate_and_a_runnable_plan_an_app(self):
        """repair round 1: a missing plate passed (the runner opens inp["plate"]); a list / dict plate raised
        TypeError; an input without a plan-level app gave 'a None plan runs only None steps'"""
        self.assertTrue(any("plate None" in x for x in flags(plan(input={"text": "HELLO"}))))
        for bad in (["photo"], {"photo": 1}):
            out = flags(plan(input={"plate": bad}))  # no TypeError
            self.assertEqual(len(out), 1, out)
        out = flags({"input": {"plate": "photo"}, "steps": [dict(GB, app="PS")]})
        self.assertTrue(any('needs "app"' in x for x in out), out)
        self.assertFalse(any("None" in x for x in out), out)
        self.assertEqual(flags(plan(dict(GB, settings={"radius": 3}), input={"plate": "photo"})), [])

    def test_name_contradicting_the_id_and_an_unknown_id(self):
        self.assertTrue(any("not 'Motion Blur'" in x for x in flags(plan(dict(GB, name="Motion Blur")))))
        e = flags(plan({"kind": "ps_tool", "id": "noSuchTool"}))
        self.assertTrue(e and "ambiguous" not in e[0] and "no PS ps_tool" in e[0], e)

    def test_check_cli_reads_bom_and_utf16_and_separates_exit_codes(self):
        body = json.dumps(plan(dict(GB, settings={"radius": 3})))
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "bom.json").write_bytes(b"\xef\xbb\xbf" + body.encode())
            (t / "u16.json").write_bytes(body.encode("utf-16"))
            (t / "bad.json").write_text("{\"app\": ", encoding="utf-8")
            (t / "empty.json").write_text(json.dumps({"app": "PS", "steps": []}), encoding="utf-8")
            self.assertEqual(run("pgd.py", "check", t / "bom.json").returncode, 0)
            self.assertEqual(run("pgd.py", "check", t / "u16.json").returncode, 0)
            self.assertEqual(run("pgd.py", "check", t / "bad.json").returncode, 2)
            self.assertEqual(run("pgd.py", "check", t / "nowhere.json").returncode, 2)
            r = run("pgd.py", "check", t / "empty.json")
            self.assertEqual(r.returncode, 1)
            self.assertIn("empty", r.stdout)


class PlanRunnable(unittest.TestCase):
    """the rules for runnable plans follow what each backend really does"""

    def test_first_untargeted_style_acts_on_the_plates_active_layer(self):
        self.assertTrue(flags(plan(LS(STROKE()), LS(SHADOW(), target="photo"), input={"plate": "photo"})))
        self.assertTrue(flags(plan(LS(STROKE()), LS(SHADOW(), target="type"), input={"plate": "text"})))
        gs = next((it for it in pgd.harvest().get(("AI", "ai_preset"), {}).values()
                   if it.get("category") == "Graphic Style"), None)
        if gs:
            self.assertTrue(flags(plan({"kind": "ai_preset", "id": gs["id"]}, {"kind": "ai_preset", "id": gs["id"],
                                       "target": "art"}, app="AI", input={"plate": "vector"})))

    def test_a_baked_or_embedded_style_and_a_script_result_are_new_targets(self):
        for mid in ({"kind": "ps_menu", "id": "3557", "target": "photo"},    # Rasterize Layer Style
                    {"kind": "ps_menu", "id": "2980", "target": "photo"}):   # Convert to Smart Object
            self.assertEqual(flags(plan(LS(STROKE(), target="photo"), mid, LS(SHADOW(), target="photo"),
                                        input={"plate": "photo"})), [], mid)
        dup = {"kind": "ps_api", "id": "class:Selection", "script": "d.activeLayer = L.duplicate();", "as": "new"}
        self.assertEqual(flags(plan(LS(STROKE(), target="photo"), dup, LS(SHADOW(), target="new"),
                                    input={"plate": "photo"})), [])

    def test_labels_per_app(self):
        cdr_fx = {"kind": "cdr_effect", "id": "a0f20985-2078-4629-98ed-ffc91fa4c0bd"}
        self.assertTrue(flags(plan(dict(cdr_fx, target="art"), app="CDR", input={"plate": "vector"})))
        self.assertEqual(flags(plan(dict(cdr_fx, target="background"), app="CDR",
                                    input={"plate": "photo", "background": "#000000"})), [])
        ai_fx = {"kind": "ai_effect", "id": "Live Adobe PSL Gaussian Blur"}
        self.assertEqual(flags(plan(dict(ai_fx, target="background"), app="AI",
                                    input={"plate": "photo", "background": "#000000"})), [])
        self.assertTrue(flags(plan(GB, input={"plate": "vector"})))  # Photoshop has no vector plate
        for app, kind in (("PS", "ps_api"), ("AI", "ai_api")):
            sc = {"kind": kind, "id": "class:Document", "script": "x", "labels": ["bar"]}
            self.assertTrue(any("CorelDRAW-only" in x for x in flags(plan(sc, app=app))), app)

    def test_runnable_plan_runs_only_its_apps_steps(self):
        st = {"app": "AI", "kind": "ai_effect", "id": "Live Adobe PSL Gaussian Blur"}
        self.assertTrue(flags(plan(st, input={"plate": "photo"})))
        self.assertEqual(flags(plan(st)), [])  # a design plan without an input may mix apps

    def test_shadow_under_stroke_by_label_soft_shadow_and_bad_values(self):
        hidden = lambda *x: any("hidden under the stroke" in i for i in flags(plan(LS(*x))))  # noqa: E731
        self.assertTrue(hidden(STROKE(style="outside", size=16), SHADOW(distance=8)))
        self.assertTrue(hidden(STROKE(style="center", size=16), SHADOW(distance=6)))
        self.assertFalse(hidden(STROKE(style="outsetFrame", size=4), SHADOW(distance=3, blur=60)))
        for bad in (STROKE(style="outsetFrame", size="16"), ):
            out = flags(plan(LS(bad, SHADOW(distance="8"))))  # reported, no TypeError
            self.assertTrue(any("expects a number" in x for x in out), out)

    def test_cdr_required_follows_the_harvest(self):
        two = {"kind": "cdr_effect", "id": "vector:Transparency:TwoColor",
               "settings": {"PatternCanvasIndex": 1, "Front": 0, "Back": 100, "TransformWithShape": False}}
        self.assertFalse([x for x in flags(plan(two, app="CDR")) if "needs" in x])
        self.assertTrue(any("needs Value" in x for x in flags(plan({"kind": "cdr_effect",
                                                                     "id": "vector:Transparency:Uniform"}, app="CDR"))))
        persp = {"kind": "cdr_effect", "id": "vector:Perspective", "settings": {"HorizVanishPointX": 2.5}}
        self.assertFalse([x for x in flags(plan(persp, app="CDR")) if "cannot be set" in x])
        self.assertTrue(flags(plan(dict(persp, settings={"HorizVanishPointX": "far"}), app="CDR")))


class Search(unittest.TestCase):
    def test_whole_words_count_once(self):
        top = lambda q, app=None: pgd.find(q, app)[0]  # noqa: E731
        self.assertIn("Sharpen", top("sharpen a photo", "PS")["name"])
        self.assertNotEqual(top("trace logo", "AI")["name"], "Analogous")
        self.assertEqual(top("Neon tube glow")["id"], "recipe:text_effects:neon_glow")
        self.assertEqual(pgd.find("a"), [])

    def test_kind_and_status_priors(self):
        top = pgd.find("drop shadow", "AI")[0]
        self.assertEqual((top["kind"], top["status"]), ("ai_effect", "current"))
        self.assertIn("Extrude", [c["name"] for c in pgd.find("3D extruded text", "CDR")[:3]])
        self.assertEqual(pgd.find("IVGTraceSettings")[0]["name"], "IVGTraceSettings")  # API cards stay findable

    def test_recipes_count_for_their_apps(self):
        self.assertTrue(pgd.find("glow", kind="recipe", app="PS"))
        self.assertEqual(pgd.card("Neon tube glow", "PS")["id"], "recipe:text_effects:neon_glow")

    def test_cache_follows_the_card_list(self):
        pgd.find("blur")
        pgd.cards.cache_clear()
        self.assertTrue(pgd.find("blur"))


class Cards(unittest.TestCase):
    def test_card_ranking_and_app_filter(self):
        self.assertIsNone(pgd.card(""))
        self.assertIsNone(pgd.card("Outer Glow", "CDR"))  # no CorelDRAW card of that name: not an AI one
        self.assertEqual(pgd.card("Screen")["kind"], "ai_blend_mode")
        self.assertEqual(pgd.card("Polygon", "CDR")["kind"], "cdr_tool")

    def test_equiv_follows_the_source_tier_and_skips_unusable_back_links(self):
        e = pgd.equiv("COLORBLEND")
        self.assertIn("ps_blend_mode", e["PS"])
        self.assertIn("ai_blend_mode", pgd.equiv("lens:cdrLensColorAdd")["AI"])
        self.assertIn("ai_api", pgd.equiv("IVGColor")["AI"])  # api -> api stays
        self.assertTrue(pgd.equiv("Black & White", "PS")["PS"].startswith("Black & White [ps_adjustment"))
        usable = {f"{c['name']} [{c['kind']} {c['id']}]" for c in pgd.cards() if c.get("status") in pgd.USABLE}
        self.assertTrue(set(pgd.equiv("Filter/Sharpen/Unsharp Mask").values()) <= usable)

    def test_brightness_contrast_layer_maps_to_a_usable_cdr_card(self):
        c = pgd.card("adjustmentLayer:brightnessEvent", "PS")
        self.assertEqual(c["equivalents"]["CDR"], "Effects/Adjust/Light")
        self.assertEqual(pgd.card("Effects/Adjust/Light", "CDR")["status"], "current")


class PgdCli(unittest.TestCase):
    def test_usage_errors_exit_2(self):
        for args in (("chek", "x.json"), ("Check", "x.json"), ("find",), ("card",), ("check",), ("equiv",),
                     ("items",), ("items", "photoshop", "blur"), ("card", "Gaussian Blur", "photoshop")):
            self.assertEqual(run("pgd.py", *args).returncode, 2, args)
        r = run("pgd.py", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("pgd.py find", r.stdout)

    def test_apps_any_case_and_unquoted_words(self):
        self.assertEqual(json.loads(run("pgd.py", "card", "Gaussian Blur", "ps").stdout)["app"], "PS")
        self.assertTrue(run("pgd.py", "items", "ps", "gaussian blur").stdout.strip())
        lines = run("pgd.py", "find", "gaussian", "blur", "ps").stdout.splitlines()
        self.assertTrue(lines and all(ln.startswith("[PS ") or ln.startswith("[multi ") for ln in lines), lines[:3])
        rec = run("pgd.py", "find", "risograph", "recipe").stdout.splitlines()
        self.assertTrue(rec and all(" recipe" in ln.split("]")[0] for ln in rec), rec)
        e = json.loads(run("pgd.py", "equiv", "Black & White", "PS").stdout)
        self.assertIn("ps_adjustment", e["PS"])

    def test_unreadable_data_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            self.assertEqual(run("pgd.py", "find", "blur", env={"PGD_HOME": str(t / "nowhere")}).returncode, 2)
            (t / "cards").mkdir()
            (t / "cards" / "a.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"cards": [
                {"name": "Thing", "id": "t", "app": "PS", "kind": "ps_menu", "summary": "glow"}]}).encode())
            (t / "cards" / "b.json").write_text('{"cards": [', encoding="utf-8")
            r = run("pgd.py", "find", "glow", env={"PGD_HOME": str(t)})
            self.assertIn("Thing", r.stdout)                 # a BOM file is read
            self.assertIn("b.json is unreadable", r.stderr)  # a broken one is reported
            (t / "p.json").write_text(json.dumps({"app": "PS", "steps": []}), encoding="utf-8")
            r = run("pgd.py", "check", t / "p.json", env={"PGD_HOME": str(t)})
            self.assertEqual(r.returncode, 1)
            self.assertIn("cards/b.json: unreadable", r.stdout)

    def test_find_refuses_an_unknown_app_or_kind_word(self):
        """final pass: a full app name or a typo'd kind became a query word, so the filter was dropped, exit 0"""
        for args in (("gaussian blur", "PHOTOSHOP"), ("blur", "PS", "ps_filtr"), ("glow", "illustrator")):
            r = run("pgd.py", "find", *args)
            self.assertEqual(r.returncode, 2, (args, r.stdout[:200]))
            self.assertIn("unknown app or kind", r.stderr)
        lines = run("pgd.py", "find", "blur", "PS", "ps_filter").stdout.splitlines()
        self.assertTrue(lines and all(ln.startswith("[PS ps_filter") for ln in lines), lines[:3])


class CardFile(unittest.TestCase):
    """run_plan.py on a temp copy of one recipe file"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "cards").mkdir()
        for n in ("recipe_text_effects.json", "recipe_retouch_cleanup.json"):
            shutil.copy(ROOT / "cards" / n, self.tmp / "cards")
        shutil.copytree(ROOT / "harvest", self.tmp / "harvest")
        self.card = self.tmp / "cards" / "recipe_text_effects.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rp(self, *args):
        return run("run_plan.py", *args, env={"PGD_HOME": str(self.tmp)})

    def r(self):
        r = rp()
        r.HOME = self.tmp
        r._Lock.path = self.tmp / "work" / "plans" / "cards.lock"
        r.pgd.HERE = self.tmp
        r.pgd.cards.cache_clear()
        r.pgd.harvest.cache_clear()
        self.addCleanup(lambda: (setattr(r.pgd, "HERE", ROOT), r.pgd.cards.cache_clear(), r.pgd.harvest.cache_clear()))
        return r

    def plan_of(self, key="neon_glow"):
        doc = json.loads(self.card.read_text(encoding="utf-8"))
        return next(c for c in doc["cards"] if c["id"] == f"recipe:text_effects:{key}")["plans"]["PS"]

    def test_one_recipe_verbs_refuse_a_family_and_take_comma_names(self):
        before = self.card.read_bytes()
        f = self.tmp / "p.json"
        f.write_text(json.dumps(self.plan_of("gold_metallic")), encoding="utf-8")
        for args in (("put", "text_effects", "PS", f), ("judge", "all", "PS", "--verdict", "broken", "--note", "x",
                                                         "--by", "t"), ("get", "text_effects", "PS"), ("get", ",", "PS")):
            self.assertEqual(self.rp(*args).returncode, 2, args)
        self.assertEqual(before, self.card.read_bytes())
        g = self.rp("get", "Scan clean-up: dust, scratches and moire", "PS")
        self.assertEqual(g.returncode, 0, g.stderr)
        self.assertIn("steps", json.loads(g.stdout))

    def test_cli_app_slots_and_selectors(self):
        for args in (("run", "", "PS"), ("run", "all", "photoshop"), ("run", ",", "PS"), ("list", "photoshop"),
                     ("show", "text_effects.neon_glow", "photoshop"), ("get", "text_effects.neon_glow"),
                     ("get", "retouch_cleanup.denoise", "AI"), ("run", "text_effects.neon_glow", "XX")):
            self.assertEqual(self.rp(*args).returncode, 2, args)
        self.assertEqual(self.rp("show", "text_effects.neon_glow", "ps").returncode, 0)

    def test_run_exit_code(self):
        r = self.r()

        class Sess:
            version = "x"

            def quit(self):
                pass

            def recover(self, e):
                pass
        r.backend = lambda a: type("B", (), {"Session": Sess})
        (self.tmp / "media").mkdir()
        (self.tmp / "media" / "plate_photo.png").write_bytes(b"x")
        r.run_one = mock.Mock(side_effect=RuntimeError("boom"))
        self.assertEqual(r.cmd_run("text_effects.neon_glow", ["PS"], force=True), 1)
        r.run_one = mock.Mock(return_value={"result": "failed", "secs": 0})
        self.assertEqual(r.cmd_run("text_effects.neon_glow", ["PS"], force=True), 1)
        r.run_one = mock.Mock(return_value={"result": "partial", "secs": 0})
        self.assertEqual(r.cmd_run("text_effects.neon_glow", ["PS"], force=True), 0)

    def test_put_checks_what_will_run(self):
        f = self.tmp / "p.json"
        good = {k: v for k, v in self.plan_of().items() if k not in ("run", "verified")}
        for bad in (dict(good, app="AI"),                                                    # another app's plan
                    dict(good, steps=good["steps"] + [{"app": "AI", "kind": "ai_effect",
                                                       "id": "Live Adobe PSL Gaussian Blur"}]),
                    {"app": "PS", "steps": [dict(GB, target="type layer")]},                # default input: text plate
                    dict(good, steps=[dict(good["steps"][0], note="\u0393\u00c7\u00a3quote\u0393\u00c7\u00a5")]
                         + good["steps"][1:])):
            f.write_text(json.dumps(bad), encoding="utf-8")
            p = self.rp("put", "text_effects.neon_glow", "PS", f)
            self.assertEqual(p.returncode, 1, (bad, p.stdout))
            self.assertIn("NOT SAVED", p.stdout)
        f.write_bytes(json.dumps(good).encode("utf-16"))  # a PowerShell redirect writes UTF-16
        self.assertEqual(self.rp("put", "text_effects.neon_glow", "PS", f).returncode, 0)
        f.write_bytes(b"\xef\xbb\xbf" + json.dumps(good).encode())  # ... or UTF-8 with a BOM
        self.assertEqual(self.rp("put", "text_effects.neon_glow", "PS", f).returncode, 0)
        out = self.tmp / "got.json"
        self.assertEqual(self.rp("get", "text_effects.neon_glow", "PS", out).returncode, 0)
        self.assertFalse(out.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["steps"], good["steps"])

    def test_card_files_stay_strict_json_and_survive_a_reader(self):
        r = self.r()
        with self.assertRaises(ValueError):
            r.record("recipe:text_effects:neon_glow", "PS", "x", NAN)
        json.loads(self.card.read_text(encoding="utf-8"), parse_constant=lambda c: self.fail(c))
        real, calls = Path.replace, []

        def flaky(self_, target):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(5, "Access is denied")
            return real(self_, target)
        with mock.patch.object(Path, "replace", flaky):
            r.record("recipe:text_effects:neon_glow", "PS", "note", "kept")
        self.assertEqual(self.plan_of()["note"], "kept")

    def test_a_new_run_retires_the_verdict_and_judge_keeps_history(self):
        r = self.r()
        rid = "recipe:text_effects:neon_glow"
        old = self.plan_of()
        self.assertIn("verified", old)
        h = r.plan_hash(old)
        r.record(rid, "PS", "run", dict(old["run"], plan_hash=h, result="failed"))
        new = self.plan_of()
        self.assertNotIn("verified", new)
        self.assertEqual(new["verified_history"][-1], old["verified"])
        self.assertEqual(r.plan_hash(new), h)  # the history is a record, not part of what runs
        self.assertNotEqual(self.rp("judge", "text_effects.neon_glow", "PS", "--verdict", "pass").returncode, 0)
        self.assertEqual(self.rp("judge", "text_effects.neon_glow", "PS", "--verdict", "weak", "--note", "a",
                                 "--by", "j").returncode, 0)
        self.assertEqual(self.rp("judge", "text_effects.neon_glow", "PS", "--verdict", "pass", "--note", "b",
                                 "--by", "j").returncode, 0)
        v = self.plan_of()["verified"]
        self.assertEqual((v["verdict"], v["previous"]["verdict"]), ("pass", "weak"))

    def test_lock_is_exclusive_and_released(self):
        r = self.r()
        with r._Lock():
            other = r._Lock()
            other.f = open(other.path, "a+b")
            try:
                with self.assertRaises(OSError):
                    other._os_lock(True)
            finally:
                other.f.close()
        with r._Lock():
            pass

    def test_public_scrubs_spaced_profiles_unc_and_posix_paths(self):
        r = self.r()
        b = chr(92)  # the paths are built, not written out: tests/test_public_scrub.py reads this file
        prof = b.join(["C:", "Users", "Jane Doe"])
        temp = b.join([prof, "App" + "Data", "Local", "Temp"])
        env = {"USERPROFILE": prof, "HOME": prof, "TEMP": temp, "TMP": temp}
        with mock.patch.dict(os.environ, env), mock.patch("os.path.expanduser", lambda p: prof):
            for s in ("cannot open " + b.join([prof, "Documents", "x.psd"]), b.join([temp, "pgd 1.png"]),
                      b * 2 + b.join(["fileserver", "clients", "Acme", "proof.png"]),
                      "/c/" + "Users/jane/OneDrive/Desktop/out.png"):
                out = r.public(s)
                self.assertNotIn("Doe", out)
                self.assertNotIn("Acme", out)
                self.assertNotIn("jane", out)
                self.assertIn("<local path>", out)
        self.assertEqual(r.public("16:9 at 10:30"), "16:9 at 10:30")
        other = b.join(["C:", "Users", "Ann Lee", "Desktop", "a.png"])  # a spaced profile that is not this machine's
        for s in ("see " + other, "see " + other.replace(b, "/"), "cannot open " + other.replace(b, b * 2)):
            out = r.public(s)
            self.assertNotIn("Lee", out)
            self.assertTrue(out.endswith(" <local path>"), out)
        # final pass: a spaced name in the POSIX form, and a client-named file under a spaced system folder
        self.assertEqual(r.public("/c/" + "Users/Jane Doe/Desktop/out.png ok"), "<local path> ok")
        self.assertEqual(r.public("at /home/jane then"), "at <local path> then")
        pf = b.join(["C:", "Program Files", "Adobe", "Adobe Photoshop 2026", "Presets", "Brushes", "My Client Set.abr"])
        for s in (pf, pf.replace(b, b * 2), pf.replace("Program Files", "Program Files (x86)")):
            self.assertEqual(r.public(f"File {s} not found"), "File <local path> not found")

    def test_recipes_fail_closed_on_a_missing_or_unreadable_card_file(self):
        """final pass: run_plan.py never asked pgd which card files it could not read, so a truncated recipe file
        (or a mistyped PGD_HOME) gave a shorter list / fewer runs with exit 0"""
        self.assertEqual(run("run_plan.py", "list", env={"PGD_HOME": str(self.tmp / "nowhere")}).returncode, 2)
        f = self.tmp / "cards" / "recipe_retouch_cleanup.json"
        f.write_bytes(f.read_bytes()[:3000])
        for args in (("list", "PS"), ("show", "text_effects.neon_glow", "PS"), ("list",)):  # (never "run": live)
            p = self.rp(*args)
            self.assertEqual(p.returncode, 2, args)
            self.assertIn("recipe_retouch_cleanup.json", p.stderr)
        with self.assertRaises(SystemExit):
            self.r().recipes()

    def test_recipes_fail_closed_on_a_missing_or_unreadable_harvest(self):
        """final check: the plan compiler routes steps through the harvest; a truncated harvest file or no harvest/
        folder turned routed steps into manual ones (cutout_social.background_blur 12/12 -> 11/12) with exit 0"""
        h = self.tmp / "harvest" / "ps" / "ps_filter.json"
        h.write_bytes(h.read_bytes()[:5000])
        p = self.rp("list", "PS")
        self.assertEqual(p.returncode, 2)
        self.assertIn("ps_filter.json", p.stderr)
        shutil.rmtree(self.tmp / "harvest")
        p = self.rp("list", "PS")
        self.assertEqual(p.returncode, 2)
        self.assertIn("harvest/", p.stderr)

    @unittest.skipUnless(DEPS, "Pillow / numpy not installed (run_one writes the frames)")
    def test_a_step_run_without_its_settings_makes_the_run_partial(self):
        """final pass: the PS / AI backends drop a value they cannot send and still say 'ok'; the run said complete"""
        from PIL import Image
        r = self.r()
        r.OUT = self.tmp / "gallery" / "recipes"
        rec = next(c for c in r.recipes() if c["id"] == "recipe:text_effects:neon_glow")
        r.compile_plan = lambda recipe, app: [{"step": 1, "kind": "ps_adjustment", "label": "Curves", "target": None,
                                               "as": None, "op": {"mode": "x"}, "manual": None,
                                               "untyped": ["curve: expects a list"]}]

        class Sess:
            version = "x"

            def open(self, inp):
                return {"type": 1}

            def snap(self, p, w=480):
                Image.new("RGB", (16, 9)).save(p)

            def step(self, cs, target, labels=None):
                return "ok", "settings not sent: curve: expects a list", None

            def export(self, p):
                Image.new("RGB", (192, 108)).save(p)
                return ["type"]

            def close(self):
                pass
        res = {app: r.run_one(Sess(), dict(rec, plans={app: rec["plans"]["PS"]}), app, do_record=False)
               for app in ("PS", "AI", "CDR")}
        self.assertEqual(res["PS"]["steps"][0].get("unsent"), True)
        self.assertEqual((res["PS"]["result"], res["AI"]["result"]), ("partial", "partial"))
        self.assertEqual(res["CDR"]["result"], "complete")  # CorelDRAW's gallery-form notes are by design


class Skeleton(unittest.TestCase):
    def test_rerunning_the_skeleton_stage_changes_no_tracked_card(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / "cards").mkdir()
            xs = sorted((ROOT / "cards").glob("*_x*.json"))
            for f in xs:
                shutil.copy(f, home / "cards" / f.name)
            shutil.copytree(ROOT / "harvest", home / "harvest")
            env = {"PGD_HOME": str(home)}
            self.assertEqual(run("prepare_batches.py", env=env).returncode, 0)
            r = run("skeleton_cards.py", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            for f in xs:
                self.assertEqual((home / "cards" / f.name).read_bytes(), f.read_bytes(), f.name)
        lesson = next(c for c in json.loads((ROOT / "cards" / "ps_api_x01.json").read_text(encoding="utf-8"))["cards"]
                      if c["id"] == "enum:RasterizeType")
        self.assertTrue(any("Invalid enumeration value" in g for g in lesson.get("gotchas") or []))


class Pipeline(unittest.TestCase):
    def test_docs_stage_writes_the_homes_readme_only(self):
        import pipeline
        code_readme = (ROOT / "README.md").read_bytes()
        try:
            with tempfile.TemporaryDirectory() as t:
                home = Path(t)
                (home / "README.md").write_text("x\n<!-- coverage:start -->\nold\n<!-- coverage:end -->\n",
                                                encoding="utf-8")
                pipeline.readme_block(home)  # no gallery/ or work/batches: left as it is
                self.assertIn("old", (home / "README.md").read_text(encoding="utf-8"))
                (home / "gallery").mkdir()
                (home / "work" / "batches").mkdir(parents=True)
                pipeline.readme_block(home)
                self.assertIn("| stage | type |", (home / "README.md").read_text(encoding="utf-8"))
            self.assertEqual((ROOT / "README.md").read_bytes(), code_readme)
        finally:
            if (ROOT / "README.md").read_bytes() != code_readme:
                (ROOT / "README.md").write_bytes(code_readme)

    def test_doctor_names_the_photo_plate_and_numpy(self):
        out = run("pipeline.py", "doctor").stdout
        self.assertIn("photo plate", out)
        self.assertIn("module numpy", out)


class BuildDocs(unittest.TestCase):
    def test_help_and_destination_guard(self):
        with tempfile.TemporaryDirectory() as t:
            r = run("build_docs.py", "--help", env={"PGD_HOME": t})
            self.assertEqual(r.returncode, 0)
            self.assertFalse((ROOT / "--help").exists())
            self.assertEqual(run("build_docs.py", Path(t) / "x.json", env={"PGD_HOME": t}).returncode, 2)
            (Path(t) / "README.md").write_text("keep", encoding="utf-8")
            self.assertEqual(run("build_docs.py", Path(t) / "README.md", env={"PGD_HOME": t}).returncode, 2)
            self.assertEqual((Path(t) / "README.md").read_text(encoding="utf-8"), "keep")

    def test_legend_and_critic_are_readable(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / "cards").mkdir()
            (home / "cards" / "zz_critic.json").write_text(json.dumps({"gaps": [
                {"gap": "open gap text"}, {"gap": "closed gap text", "fixed": "done"}], "weak_cards": ["plain"]}),
                encoding="utf-8")
            out = home / "PGD.md"
            self.assertEqual(run("build_docs.py", out, env={"PGD_HOME": str(home)}).returncode, 0)
            md = out.read_text(encoding="utf-8")
        self.assertNotIn('{"gap"', md)
        self.assertIn("- open gap text", md)
        self.assertIn("Closed since", md)
        self.assertNotIn("Blank = not rendered (tools, menus, presets", md)


class Harvest(unittest.TestCase):
    def test_a_cdr_reharvest_keeps_the_proven_cmd_forms(self):
        """repair round 1: extra.cmd_form had no tracked writer, so a live re-harvest dropped every proven form"""
        with mock.patch.object(sys, "path", list(sys.path)):  # the tool puts tools/cdr on sys.path
            he = load_tool("cdr", "harvest_effects")
        old = json.loads((ROOT / "harvest" / "cdr" / "cdr_effect.json").read_text(encoding="utf-8"))
        proven = {it["id"]: it["extra"]["cmd_form"] for it in old["items"] if (it.get("extra") or {}).get("cmd_form")}
        self.assertTrue(proven)
        fresh = [dict(it, extra={k: v for k, v in (it.get("extra") or {}).items() if k != "cmd_form"})
                 for it in old["items"]]
        he.keep_cmd_forms(fresh, old)
        self.assertEqual({it["id"]: it["extra"]["cmd_form"] for it in fresh if it["extra"].get("cmd_form")}, proven)
        self.assertEqual(he.keep_cmd_forms(fresh[:1], {}), fresh[:1])  # first harvest: nothing to keep
        import inspect  # final pass: main() must call the helper, before it writes the harvest file
        src = inspect.getsource(he.main)
        self.assertLess(src.index("keep_cmd_forms(items, load(OUT"), src.index("OUT.write_text"))


class CardText(unittest.TestCase):
    def test_work_paths_are_marked_local_and_old_frame_pointers_blank(self):
        """final pass: 154 verified.previous.frame values pointed into the unshipped work/ folder"""
        b = {"kind": "ps_preset", "app": "PS", "tier": "preset", "items": [{"name": "X", "id": "x"}]}
        good = {"name": "X", "id": "x", "app": "PS", "kind": "ps_preset", "status": "current", "summary": "s",
                "use_for": ["u"], "confidence": "high", "applies_to": "pixel layer"}
        self.assertEqual(validate_cards.check(b, [good]), [])
        old = dict(good, verified={"verdict": "pass", "previous": {"frame": "work/ps/gallery/pre_fix/a.png"}})
        self.assertTrue(any("under work/" in i for i in validate_cards.check(b, [old])))
        ok = dict(good, summary="read in work/ps/p.json (a local file, not shipped); FrameWork/LockToolbars",
                  plans={"PS": {"steps": [{"script": "save('work/plans/out/x.pdf')"}]}})
        self.assertEqual(validate_cards.check(b, [ok]), [])
        for f in sorted((ROOT / "cards").glob("*.json")):
            if f.stem != "zz_critic":
                for c in json.loads(f.read_bytes())["cards"]:
                    self.assertEqual(validate_cards.unshipped(c), [], (f.name, c.get("id")))


class Parsers(unittest.TestCase):
    def test_cdr_package_members_are_read_bounded(self):
        """final pass: zcf_meta / color.xml / document.cdss and the preview reads still inflated whole members"""
        import inspect, re
        hp = load_tool("cdr", "harvest_presets")
        self.assertFalse(re.search(r"\bz\.read\([^)]", inspect.getsource(hp)))
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "m.zip"
            with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("META-INF/metadata.xml", "<x>" + " " * (5 << 20) + "</x>")
            with zipfile.ZipFile(f) as z, self.assertRaises(ValueError):
                hp.zcf_meta(z)
            with zipfile.ZipFile(f) as z, self.assertRaises(KeyError):
                hp.zread(z, "color/color.xml")  # a missing member still raises KeyError, as z.read did


@unittest.skipUnless(DEPS, "Pillow / numpy not installed (the backends and renderers need them)")
class Backends(unittest.TestCase):
    def test_cdr_proven_form_without_a_gallery(self):
        b = rp().backend("CDR")
        out, forms = b.eg.OUT, b._FORMS
        try:
            b.eg.OUT, b._FORMS = ROOT / "work" / "no_such_gallery", None  # a fresh clone has no gallery/
            emb = next(i for i in pgd.harvest()[("CDR", "cdr_effect")].values() if i["name"] == "Emboss")
            cs = b.compile_steps({"steps": [{"kind": "cdr_effect", "id": emb["id"],
                                             "settings": {"ColorMode": "Black"}}]}, {"plate": "photo"})
            self.assertIn("ColorMode=2", cs[0]["op"]["cmd"])
        finally:
            b.eg.OUT, b._FORMS = out, forms

    def test_cdr_command_refuses_injected_keys(self):
        b = rp().backend("CDR")
        cm = next(i for i in pgd.harvest()[("CDR", "cdr_effect")].values() if i["name"] == "Channel Mixer")
        cs = b.compile_steps({"steps": [{"kind": "cdr_effect", "id": cm["id"],
                                         "settings": {"TotalPercentText": "1,Foo=2"}}]}, {"plate": "photo"})
        self.assertIn("cannot travel", cs[0].get("error") or "")
        with self.assertRaises(ValueError):
            b.eg.fmt(NAN)

    def test_ai_live_effect_xml_stays_well_formed(self):
        import xml.etree.ElementTree as ET
        b = rp().backend("AI")
        it = pgd.harvest()[("AI", "ai_effect")]["Live Adobe Geometry3D Extrude"]
        for s in ("a&b", "x<y"):
            pl = b.effect_plan(it, {"Geometry3DkSunlightNameKey": s})
            if pl.get("xml"):
                ET.fromstring(pl["xml"])  # the value went by the text route, not into the Dict data attribute

    def test_ai_result_with_control_characters_parses(self):
        b = rp().backend("AI")
        with mock.patch.object(b.eg, "run", lambda *a, **k: ('{"say":"tab\there"}', None, [])):
            res, err = b.eg.call("x.ai", "")
        self.assertEqual((res.get("say"), err), ("tab\there", None))

    def test_parsers_refuse_truncated_and_oversized_input(self):
        g = load_tool("ps", "preset_gallery")
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "c.shc").write_bytes(b"\x00\x00" + "$$$/Contour/x".encode("utf-16-be"))
            with self.assertRaises(ValueError):
                g.shc_curves(t / "c.shc")
            hp = load_tool("cdr", "harvest_presets")
            name = b"CPresetThing"
            body = (b"\x00" * 4 + len(name).to_bytes(2, "little") + name + b"\x00" * 16
                    + zlib.compress(b"\x00" * (8 << 20), 9).replace(b"\x78\xda", b"\x78\x5e", 1))
            (t / "bomb.pst").write_bytes(body)
            with self.assertRaises(ValueError):
                hp.pst_info(t / "bomb.pst")
            with zipfile.ZipFile(t / "f.zip", "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("content/fill.xml", "<fill>" + " " * (5 << 20) + "</fill>")
            with zipfile.ZipFile(t / "f.zip") as z, self.assertRaises(ValueError):
                hp.fill_info(z)
        ap = load_tool("ai", "ai_presets")
        with mock.patch.object(ap, "_streams", lambda b, h: (0, [1], [(b"\x5d\x00\x00\x01\x00", 1 << 40)])), \
                mock.patch.object(ap, "_lzma", mock.Mock(side_effect=AssertionError("decoded"))), \
                tempfile.TemporaryDirectory() as t:
            f = Path(t) / "x.sbsar"
            f.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 6 + (0).to_bytes(8, "little") + (1).to_bytes(8, "little")
                          + b"\x00" * 4 + b"\x17")
            with self.assertRaises(ValueError):
                ap.sbsar_xml(f)

    def test_cdr_preset_previews_are_read_bounded(self):
        """final pass: Template / Sprayer / Fill previews were inflated whole (z.read) before PIL looked at them"""
        import inspect, re
        g = load_tool("cdr", "preset_gallery")
        self.assertFalse(re.search(r"\bz\.read\([^)]", inspect.getsource(g)))
        failed = {}
        st = type("St", (), {"done": lambda s, i: False, "put": lambda s, it, im, how: failed.setdefault("put", how),
                             "fail": lambda s, it, why: failed.setdefault(it["id"], why), "save": lambda s: None})()
        with tempfile.TemporaryDirectory() as t, mock.patch.object(g, "MAX_PREVIEW", 100):
            f = Path(t) / "t.cdrt"
            with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("previews/page1.png", b"\x00" * 200)
            g.file_phase(st, [{"id": "t", "category": "Template", "invoke": {"file": str(f)}}])
        self.assertIn("ValueError: previews/page1.png is over", failed.get("t", ""))


if __name__ == "__main__":
    unittest.main()
