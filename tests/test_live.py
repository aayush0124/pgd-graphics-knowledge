"""Opt-in checks against the real machine (PGD_LIVE=1). They never start Photoshop, Illustrator or CorelDRAW and never
send a script to them: they confirm the apps are installed where the tools look, and that the host lock works.
The live stages themselves (harvest, galleries) run through workflows/*.js, never from tests."""
import os, subprocess, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, run  # noqa: E402

LIVE = os.environ.get("PGD_LIVE") == "1"


@unittest.skipUnless(LIVE, "live checks are opt-in: set PGD_LIVE=1")
class Live(unittest.TestCase):
    def test_doctor_finds_all_three_apps(self):
        r = run("pipeline.py", "doctor")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(r.stdout.count(" found: "), 3, r.stdout)

    @unittest.skipUnless(os.name == "nt", "the host lock is a Win32 named mutex")
    def test_hostlock_selftest(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "hostlock.py"), "--selftest"], capture_output=True,
                           text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
