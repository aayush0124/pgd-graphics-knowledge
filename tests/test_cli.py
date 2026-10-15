"""Every pgd.py subcommand, check_harvest.py, validate_cards.py, prepare_batches.py, build_docs.py and make_sheets.py:
exit codes, output shape, golden queries and negative tests. Offline; no app, network or LLM."""
import json, os, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FIX, ROOT, load_json, run  # noqa: E402

import pgd, prepare_batches, validate_cards  # noqa: E402


class PgdCli(unittest.TestCase):
    def test_no_args_prints_usage(self):
        r = run("pgd.py")
        self.assertEqual(r.returncode, 0)
        for cmd in ("find", "card", "equiv", "items", "check", "stats"):
            self.assertIn(f"pgd.py {cmd}", r.stdout)

    def test_find_golden_gaussian_blur(self):
        r = run("pgd.py", "find", "gaussian blur")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(any(ln.startswith("[PS ps_filter") and "] Gaussian Blur:" in ln for ln in lines[:5]), lines[:5])
        self.assertTrue(all(ln.startswith("[") for ln in lines))

    def test_find_golden_recipes(self):
        for query, want, family in (("flat long shadow icon", "] Flat icon with long shadow:", "vector_illustration"),
                                    ("bleed and crop marks", "] Bleed and crop marks:", "print_prep"),
                                    ("letterpress deboss", "] Letterpress deboss:", "text_effects"),
                                    ("risograph two-ink print", "] Risograph two-ink print:", "poster_print"),
                                    ("breaking-news strap", "] Breaking-news strap:", "news_editorial"),
                                    ("night time cool grade", "] Night-time cool grade:", "photo_looks"),
                                    ("scan dust scratches moire", "] Scan clean-up: dust, scratches and moire:", "retouch_cleanup"),
                                    ("sticker cut-out white outline", "] Sticker cut-out with white outline and drop shadow:", "cutout_social")):
            if not (ROOT / "cards" / f"recipe_{family}.json").exists():
                continue
            lines = run("pgd.py", "find", query).stdout.splitlines()
            self.assertTrue(any(ln.startswith("[multi recipe") and want in ln for ln in lines[:3]), (query, lines[:3]))

    def test_find_filters_app_and_kind(self):
        r = run("pgd.py", "find", "drop shadow", "AI", "ai_effect")
        self.assertEqual(r.returncode, 0)
        lines = r.stdout.splitlines()
        self.assertTrue(lines)
        self.assertTrue(all(ln.startswith("[AI ai_effect") for ln in lines), lines[:3])

    def test_card_by_name_and_by_id(self):
        a = json.loads(run("pgd.py", "card", "Gaussian Blur", "PS").stdout)
        b = json.loads(run("pgd.py", "card", "gaussianBlur").stdout)
        self.assertEqual((a["app"], a["kind"], a["id"]), ("PS", "ps_filter", "gaussianBlur"))
        self.assertEqual(a["id"], b["id"])
        for f in ("summary", "use_for", "params", "demo_settings", "scripting"):
            self.assertIn(f, a)

    def test_card_unknown_is_null(self):
        r = run("pgd.py", "card", "no such effect xyz")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "null"))

    def test_equiv_cross_app(self):
        e = json.loads(run("pgd.py", "equiv", "Gaussian Blur").stdout)
        self.assertIn("gaussianBlur", e.get("PS", ""))
        self.assertTrue({"AI", "CDR"} & set(e), e)
        self.assertTrue(all("[" in v or "(no card)" in v for v in e.values()), e)
        self.assertEqual(json.loads(run("pgd.py", "equiv", "no such effect xyz").stdout), {})

    def test_items_searches_the_harvest(self):
        r = run("pgd.py", "items", "AI", "drop shadow")
        lines = r.stdout.splitlines()
        self.assertEqual(r.returncode, 0)
        self.assertTrue(lines)
        self.assertTrue(all(ln.startswith("[ai_") and " id=" in ln and " path=" in ln for ln in lines), lines[:3])
        self.assertTrue(any(ln.startswith("[ai_effect] Drop Shadow ") for ln in lines), lines)
        self.assertEqual(run("pgd.py", "items", "CDR", "zzqx nothing").stdout.strip(), "")

    def test_check_good_plan(self):
        r = run("pgd.py", "check", FIX / "plan_good.json")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("OK", r.stdout)

    def test_check_bad_plan_flags_each_problem(self):
        r = run("pgd.py", "check", FIX / "plan_bad.json")
        self.assertEqual(r.returncode, 1)
        out = r.stdout
        self.assertIn("step 2 Gaussian Blur: Radius: 5000 above the harvested maximum", out)
        self.assertIn("step 3 Gausian Blur: no PS ps_filter by that name or id", out)
        self.assertIn("step 4 Drop Shadow: Drop Shadow has no param 'Opacity'", out)
        self.assertNotIn("step 1 ", out)
        self.assertNotIn("step 5 ", out)

    def test_check_plan_negative_cases(self):
        issues = pgd.check_plan({"steps": [
            {"kind": "ps_filter", "name": "Gaussian Blur"},                                      # no app
            {"app": "PS", "kind": "ps_filter", "name": "Gaussian Blur", "settings": {"Radius": "big"}},
            {"app": "PS", "kind": "ps_filter", "name": "Gaussian Blur", "settings": {"Radius": 0.01}},
            {"app": "XX", "kind": "ps_filter", "name": "Gaussian Blur"}]})
        text = "\n".join(issues)
        self.assertIn("step 1 Gaussian Blur: needs app", text)
        self.assertIn("step 2 Gaussian Blur: Radius: expects a number", text)
        self.assertIn("below the harvested minimum", text)
        self.assertIn("step 4 Gaussian Blur: needs app", text)
        self.assertEqual(len(issues), 4, issues)

    def test_check_plan_object_and_list_settings(self):
        curve = [{"channel": "composite", "curve": [[0, 0], [64, 40], [192, 215], [255, 255]]}]
        issues = pgd.check_plan({"app": "PS", "steps": [
            {"kind": "ps_adjustment", "id": "curves", "settings": {"adjustment": curve}},
            {"kind": "ps_adjustment", "id": "curves", "settings": {"adjustment": [{"chanel": "composite"}]}},
            {"kind": "ps_adjustment", "id": "adjustmentLayer:colorBalance", "settings": {"shadowLevels": [-40, 40]}},
            {"kind": "ps_adjustment", "id": "colorBalance", "settings": {"midtoneLevels": [0, 0.5, 0]}}]})
        text = "\n".join(issues)
        self.assertNotIn("step 1 ", text)
        self.assertIn("step 2 curves: adjustment: ['chanel'] not members", text)
        self.assertIn("step 3 adjustmentLayer:colorBalance: shadowLevels: expects a list of 3", text)
        self.assertIn("step 4 colorBalance: midtoneLevels: expects whole numbers", text)

    def test_check_plan_flags_unusable_and_broken_cards(self):
        hidden = next((c for c in pgd.cards() if c.get("status") in ("unusable", "hidden")
                       and pgd._lookup(c["app"], c["kind"], {"id": c["id"]})), None)
        broken = next((c for c in pgd.cards() if (c.get("verified") or {}).get("verdict") == "broken"
                       and c.get("status") not in ("unusable", "hidden")
                       and pgd._lookup(c["app"], c["kind"], {"id": c["id"]})), None)
        if not hidden or not broken:
            self.skipTest("no hidden / broken card in this data set")
        issues = pgd.check_plan({"steps": [{"app": c["app"], "kind": c["kind"], "id": c["id"]} for c in (hidden, broken)]})
        self.assertTrue(any(f"card status is {hidden['status']}" in x for x in issues), issues)
        self.assertTrue(any("render test failed" in x for x in issues), issues)

    def test_check_plan_flags_whole_styles_on_one_target(self):
        stroke = {"name": "Stroke", "settings": {"style": "outsetFrame", "size": 6}}
        shadow = {"name": "Drop Shadow", "settings": {"distance": 8}}
        ls = lambda s, **kw: dict({"kind": "ps_layer_style"}, **s, **kw)  # noqa: E731
        dup = {"kind": "ps_menu", "id": "1135"}  # Duplicate Layer
        blur = {"kind": "ps_filter", "id": "gaussianBlur", "settings": {"radius": 3}}

        def style_issues(*steps, app="PS"):
            return [x for x in pgd.check_plan({"app": app, "steps": list(steps)})
                    if "replaces the whole style" in x or "only one" in x]
        bad = style_issues(ls(stroke), blur, ls(shadow))  # a filter is no target change
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("step 3 Drop Shadow: replaces the whole style that step 1 gave the same target", bad[0])
        self.assertIn('"effects"', bad[0])
        self.assertTrue(style_issues(ls(stroke, target="type"), dup, ls(shadow, target="type")))  # back to "type"
        for fixed in ((ls({"effects": [stroke, shadow]}),),                                  # one combined set
                      (ls(stroke), dup, ls(shadow)),                                         # Duplicate Layer
                      (ls(stroke), {"kind": "ps_menu", "id": "6300"}, ls(shadow)),           # a new fill layer
                      (ls(stroke), ls(shadow, target="type layer")),                         # another named target
                      (ls({"effects": [shadow, dict(shadow, settings={"distance": 16})]}),)):  # dropShadowMulti
            self.assertEqual(style_issues(*fixed), [], fixed)
        self.assertEqual(pgd.check_plan({"app": "PS", "steps": [ls({"effects": [stroke, shadow]})]}), [])
        glow = {"name": "Outer Glow", "settings": {"blur": 20}}
        self.assertIn("a layer takes only one Outer Glow", " ".join(style_issues(ls({"effects": [glow, glow]}))))
        self.assertEqual(len(style_issues(ls({"effects": [stroke]}), ls({"effects": [shadow]}))), 1)

        gs = next((it for it in pgd.harvest().get(("AI", "ai_preset"), {}).values()
                   if it.get("category") == "Graphic Style"), None)
        if gs is None:
            self.skipTest("no Illustrator graphic style in this harvest")
        live, style = {"kind": "ai_effect", "id": "Live Outer Glow"}, {"kind": "ai_preset", "id": gs["id"]}
        self.assertEqual(len(style_issues(live, style, app="AI")), 1)   # the graphic style wipes the live effect
        self.assertEqual(len(style_issues(style, style, app="AI")), 1)
        self.assertEqual(style_issues(style, live, app="AI"), [])       # live effects added after the style stay
        self.assertEqual(style_issues(live, {"kind": "ai_menu", "id": "pasteFront"}, style, app="AI"), [])

    def test_find_prints_non_latin_text_on_a_cp1252_console(self):
        text = "Shapes देवनागरी headlines and Arabic-Indic digits ٠١٢٣"
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "cards").mkdir()
            (Path(t) / "cards" / "x.json").write_text(json.dumps({"cards": [
                {"name": "Complex Script Type", "id": "cst", "app": "PS", "kind": "ps_menu", "status": "current",
                 "summary": text}]}, ensure_ascii=False), encoding="utf-8")
            r = run("pgd.py", "find", "complex script", env={"PGD_HOME": t, "PYTHONIOENCODING": "cp1252"})
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertIn(f"[PS ps_menu] Complex Script Type: {text}", r.stdout)

    def test_stats_shape(self):
        r = run("pgd.py", "stats")
        s = json.loads(r.stdout)
        self.assertEqual(set(s), {"harvest", "cards", "verdicts"})
        self.assertEqual(len(s["harvest"]), 19)
        for kind, n in s["cards"].items():
            app = kind.split("_")[0].upper()
            if f"{app}:{kind}" in s["harvest"]:
                self.assertLessEqual(n, s["harvest"][f"{app}:{kind}"], kind)
        self.assertTrue(set(s["verdicts"]) <= set(validate_cards.VERDICT))


class Harvest(unittest.TestCase):
    def test_check_harvest_clean(self):
        r = run("check_harvest.py")
        self.assertEqual(r.returncode, 0, r.stdout[-2000:])
        self.assertNotIn("ERROR", r.stdout)
        self.assertEqual(len([ln for ln in r.stdout.splitlines() if " items, " in ln]), 19)

    def test_check_harvest_selftest(self):
        r = run("check_harvest.py", "--selftest")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "selftest ok"))

    def test_check_harvest_flags_a_bad_file(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "ps" / "ps_filter.json"
            p.parent.mkdir()
            p.write_text(json.dumps({"app": "PS", "kind": "ps_filter", "items": [
                {"name": "A", "id": "a", "params": [{"name": "R", "type": "float"}]}, {"name": "B", "id": "a"}]}),
                encoding="utf-8")
            r = run("check_harvest.py", p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("repeats item", r.stdout)
        self.assertIn("'float' not in", r.stdout)


class Validator(unittest.TestCase):
    def test_selftest(self):
        self.assertEqual(run("validate_cards.py", "--selftest").stdout.strip(), "selftest ok")

    def test_no_args_validates_every_card_file(self):
        r = run("validate_cards.py")
        if r.returncode:  # a card file mid-write by an agent: one retry
            r = run("validate_cards.py")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:])
        self.assertRegex(r.stdout.splitlines()[-1], r"^\d+ card files \(.*\), \d+ cards: \d+ clean, 0 with issues")

    def test_one_arg_prints_usage(self):
        r = run("validate_cards.py", "x.json")
        self.assertEqual(r.returncode, 2)
        self.assertIn("validate_cards.py --selftest", r.stdout)

    def _batch_with_cards(self):
        mem = prepare_batches.all_batches(ROOT)
        name = next(n for n in ("ps_filter_03", "ps_filter_01", "ai_effect_01") if (ROOT / "cards" / f"{n}.json").exists())
        return name, mem[name]

    def test_two_arg_form_clean(self):
        name, batch = self._batch_with_cards()
        with tempfile.TemporaryDirectory() as t:
            b = Path(t) / f"{name}.json"
            b.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            r = run("validate_cards.py", b, ROOT / "cards" / f"{name}.json")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertRegex(r.stdout.strip().splitlines()[-1], r"^\d+ cards, 0 issues$")

    def test_two_arg_form_flags_bad_cards(self):
        name, batch = self._batch_with_cards()
        cards = load_json(ROOT / "cards" / f"{name}.json")["cards"]
        cards[0] = dict(cards[0], status="live", confidence="sure", name=cards[0]["name"] + " x")
        cards.append(dict(cards[1], id="not-in-batch"))
        with tempfile.TemporaryDirectory() as t:
            b, c = Path(t) / "b.json", Path(t) / "c.json"
            b.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            c.write_text(json.dumps({"cards": cards}, ensure_ascii=False), encoding="utf-8")
            r = run("validate_cards.py", b, c)
        self.assertEqual(r.returncode, 1)
        for want in ("status 'live'", "confidence 'sure'", "must be the harvested name exactly", "is not in the batch"):
            self.assertIn(want, r.stdout)


class Batches(unittest.TestCase):
    def test_plan_covers_every_harvest_item_once(self):
        mem = prepare_batches.all_batches(ROOT)
        for f in sorted((ROOT / "harvest").glob("*/*.json")):
            d = load_json(f)
            got = [it["id"] for b in mem.values() if b["kind"] == d["kind"] for it in b["items"]]
            self.assertEqual(sorted(got), sorted(it["id"] for it in d["items"]), d["kind"])

    def test_in_memory_batches_match_work_batches(self):
        disk = ROOT / "work" / "batches"
        if not disk.exists():
            self.skipTest("no work/batches (fresh clone): the in-memory plan is the only source")
        mem = prepare_batches.all_batches(ROOT)
        names = {p.stem for p in disk.glob("*.json")}
        self.assertEqual(names, set(mem))
        for n in sorted(names):
            d = load_json(disk / f"{n}.json")
            self.assertEqual([(i["id"], i["name"], i.get("params")) for i in d["items"]],
                             [(i["id"], i["name"], i.get("params")) for i in mem[n]["items"]], n)


class Docs(unittest.TestCase):
    def test_build_docs_is_reproducible(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "home"
            (home / "cards").mkdir(parents=True)
            picked = {}  # a snapshot of two card files per kind: agents may be writing cards right now
            for f in sorted((ROOT / "cards").glob("*.json")):
                if len(picked.setdefault(f.stem.rsplit("_", 1)[0], [])) < 2:
                    picked[f.stem.rsplit("_", 1)[0]].append(f)
                    shutil.copy(f, home / "cards" / f.name)
            a, b = Path(t) / "a.md", Path(t) / "b.md"
            for out in (a, b):
                r = run("build_docs.py", out, env={"PGD_HOME": str(home)})
                self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            text = a.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# PGD: professional graphics designer knowledge base"))
        self.assertIn("## Contents", text)
        self.assertIn("## Photoshop filters", text)
        self.assertNotIn("\r\n", text)


class Sheets(unittest.TestCase):
    def test_make_sheets_on_a_tiny_gallery(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed (the sheets stage needs it)")
        import hashlib
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / "work" / "batches").mkdir(parents=True)
            g = home / "gallery" / "ps_preset"
            g.mkdir(parents=True)
            items = [{"name": f"Preset {i}", "id": f"p{i}"} for i in range(3)]
            (home / "work" / "batches" / "ps_preset_01.json").write_text(json.dumps(
                {"kind": "ps_preset", "app": "PS", "tier": "preset", "items": items}), encoding="utf-8")
            Image.new("RGB", (320, 320), "#3366FF").save(g / f"{hashlib.sha1(b'p0').hexdigest()[:12]}.png")
            (g / "index.json").write_text(json.dumps([{"id": "p0", "how": "file image"}]), encoding="utf-8")
            (g / "failed.json").write_text(json.dumps({"p1": "boom"}), encoding="utf-8")
            r = run("make_sheets.py", "ps_preset_01", env={"PGD_HOME": str(home)})
            self.assertEqual(r.returncode, 0, r.stderr)
            meta = json.loads((home / "work" / "sheets" / "ps_preset_01_sheets.json").read_text(encoding="utf-8"))
            self.assertTrue((home / "work" / "sheets" / "ps_preset_01_s1.png").exists())
        self.assertEqual([m["state"] for m in meta], ["rendered", "render failed", "no render"])


class PipelineCli(unittest.TestCase):
    def test_status_json(self):
        r = run("pipeline.py", "status", "--json")
        self.assertIn(r.returncode, (0, 10), r.stderr)
        s = json.loads(r.stdout)
        self.assertEqual([x["stage"] for x in s["stages"]],
                         ["harvest", "check_harvest", "batches", "skeleton", "cards", "validate", "galleries", "sheets",
                          "preset_cards", "verify", "recipes", "plans", "docs"])
        self.assertEqual(len(s["kinds"]), 19)
        self.assertEqual(s["harvest_errors"], 0)
        for k in s["kinds"]:
            self.assertEqual(set(k["verdicts"]), {"pass", "weak", "wrong", "broken", "not_rendered"})
            self.assertLessEqual(k["card_files"], k["batches"])

    def test_status_text_and_markdown(self):
        r = run("pipeline.py", "status")
        self.assertIn(r.returncode, (0, 10))
        self.assertIn("preset batches without cards", r.stdout)
        import pipeline
        m = pipeline.markdown(pipeline.gather(ROOT))  # the --markdown output, without a second full scan
        self.assertIn("| stage | type | state | counts |", m)
        self.assertIn("| app | kind | items |", m)
        self.assertIn("Preset batches still without cards:", m)
        self.assertEqual(pipeline._ranges(["ai_preset_18", "ai_preset_19", "ai_preset_20", "cdr_preset_02"]),
                         "ai_preset_18..20, cdr_preset_02")

    def test_run_deterministic_stage(self):
        self.assertEqual(run("pipeline.py", "run", "check_harvest").returncode, 0)

    def test_live_and_agent_stages_only_print_how(self):
        for stage, script in (("cards", "pgd_cards.js"), ("galleries", "pgd_effect_gallery.js"),
                              ("verify", "pgd_verify.js"), ("harvest", "pgd_harvest.js")):
            r = run("pipeline.py", "run", stage)
            self.assertEqual(r.returncode, 10, stage)
            self.assertIn(script, r.stdout)

    def test_unknown_stage_and_usage(self):
        self.assertEqual(run("pipeline.py", "run", "nope").returncode, 1)
        self.assertEqual(run("pipeline.py").returncode, 0)

    def test_doctor(self):
        r = run("pipeline.py", "doctor")
        self.assertIn(r.returncode, (0, 10), r.stdout)
        self.assertIn("python ", r.stdout)
        self.assertIn("free RAM", r.stdout)


if __name__ == "__main__":
    unittest.main()
