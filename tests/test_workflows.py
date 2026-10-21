"""The Claude Workflow scripts in workflows/: they parse, carry no machine paths, fail loudly without args.root, and
put the root they are given into every agent prompt. Uses node (skips when it is not installed) and
tests/workflow_harness.js, which stubs the Workflow hooks so no agent is started."""
import json, re, shutil, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = sorted((ROOT / "workflows").glob("*.js"))
HARNESS = ROOT / "tests" / "workflow_harness.js"
NODE = shutil.which("node")
FAKE = "/srv/pgd-test-root"
ARGS = {"pgd_cards.js": {"batches": ["ps_filter_01", "ps_tool_01", "ps_menu_01", "ps_api_01"]},
        "pgd_preset_cards.js": {"batches": ["ai_preset_18"], "width": 1},
        "pgd_verify.js": {"batches": ["ps_filter_01"]},
        "pgd_effect_gallery.js": {"app": "CDR"}, "pgd_preset_gallery.js": {"app": "AI"},
        "pgd_app_chain.js": {"app": "PS", "batches": ["ps_filter_01"], "scripts": FAKE + "/workflows"},
        "pgd_plans.js": {"apps": ["PS", "CDR"], "families": ["text_effects", "photo_looks"]}}


def harness(path, args):
    p = subprocess.run([NODE, str(HARNESS), str(path), args if isinstance(args, str) else json.dumps(args)],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    return json.loads(p.stdout)


class Workflows(unittest.TestCase):
    def test_there_are_workflows(self):
        self.assertGreaterEqual(len(WF), 9)

    def test_static_shape(self):
        for f in WF + [ROOT / "tests" / "workflow_harness.js"]:  # the launcher refuses a script with a CR in it
            self.assertNotIn(b"\r", f.read_bytes(), f"{f.name}: CRLF (.gitattributes keeps *.js LF)")
        for f in WF:
            src = f.read_text(encoding="utf-8")
            self.assertTrue(src.startswith("export const meta = {"), f.name)
            meta = src[:src.index("\n}\n") + 2]
            self.assertNotIn("${", meta, f"{f.name}: meta must be a pure literal")
            self.assertIn("Launch args", src, f"{f.name}: document the launch args at the top")
            self.assertIn("args.root", src, f.name)
            self.assertIsNone(re.search(r"const ROOT = ['\"]", src), f"{f.name}: ROOT must come from args")
            self.assertIsNone(re.search(r"[A-Za-z]:[\\/]+(Users|AI_" r"Systems_)", src), f"{f.name}: machine path")
            self.assertNotIn("scratch" "pad", src, f.name)

    @unittest.skipUnless(NODE, "node not installed")
    def test_scripts_parse(self):
        for f in WF:
            self.assertTrue(harness(f, "--check-only")["ok"], f.name)

    @unittest.skipUnless(NODE, "node not installed")
    def test_missing_root_fails_loudly(self):
        for f in WF:
            r = harness(f, ARGS.get(f.name, {}))
            self.assertFalse(r["ok"], f.name)
            self.assertIn("args.root", r["error"], f.name)
            self.assertEqual(r["calls"], [], f"{f.name} started work without a root")

    @unittest.skipUnless(NODE, "node not installed")
    def test_root_reaches_every_prompt(self):
        for f in WF:
            r = harness(f, dict(ARGS.get(f.name, {}), root=FAKE))
            self.assertTrue(r["ok"], f"{f.name}: {r.get('error')}")
            self.assertTrue(r["calls"], f.name)
            for c in r["calls"]:
                if c["hook"] == "agent":
                    self.assertIn(FAKE, c["prompt"], f"{f.name}: {c['label']}")
                    self.assertIsNone(re.search(r"[A-Za-z]:[\\/]+(Users|AI_" r"Systems_)", c["prompt"]), c["label"])
                else:  # pgd_app_chain.js: children come from args.scripts and get the same root
                    self.assertTrue(c["ref"]["scriptPath"].startswith(FAKE + "/workflows/"), c["ref"])
                    self.assertEqual(c["args"]["root"], FAKE)

    @unittest.skipUnless(NODE, "node not installed")
    def test_plans_one_owner_per_app_then_judges(self):
        r = harness(ROOT / "workflows" / "pgd_plans.js", dict(ARGS["pgd_plans.js"], root=FAKE))
        labels = [c["label"] for c in r["calls"] if c["hook"] == "agent"]
        for app in ("PS", "CDR"):
            mine = [x for x in labels if f":{app}:" in x]
            self.assertLess(mine.index(f"run:{app}:text_effects"), mine.index(f"run:{app}:photo_looks"), mine)
            self.assertIn(f"judge:{app}:text_effects", mine)
        self.assertNotIn("run:AI:text_effects", labels)

    @unittest.skipUnless(NODE, "node not installed")
    def test_hostlock_default_is_the_vendored_copy(self):
        r = harness(ROOT / "workflows" / "pgd_effect_gallery.js", {"root": FAKE, "app": "PS"})
        self.assertIn(f"host_lock(\"ui\") from {FAKE}/tools/hostlock.py", r["calls"][0]["prompt"])
        self.assertIn(f'sys.path.insert(0, "{FAKE}/tools")', r["calls"][0]["prompt"])
        r = harness(ROOT / "workflows" / "pgd_effect_gallery.js", {"root": FAKE, "app": "PS", "hostlock": "/x/hostlock.py"})
        self.assertIn("from /x/hostlock.py", r["calls"][0]["prompt"])


if __name__ == "__main__":
    unittest.main()
