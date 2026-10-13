"""Data integrity over every card file that exists: each validates against its batch (built in memory from the
harvest, so no work/ folder is needed), ids are unique, verdicts and app / kind values are legal per CONTRACT.md."""
import sys, unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, card_files, load_json  # noqa: E402

import check_harvest, prepare_batches, validate_cards  # noqa: E402

KINDS = check_harvest.KINDS


class Cards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batches = prepare_batches.all_batches(ROOT)
        cls.files = {f.stem: load_json(f) for f in card_files()}

    def test_there_are_cards(self):
        self.assertGreater(len(self.files), 100)

    def test_every_card_file_validates_against_its_batch(self):
        bad = {}
        for name, doc in self.files.items():
            if name in self.batches:
                iss = validate_cards.check(self.batches[name], doc.get("cards") or [])
                if iss:
                    bad[name] = iss[:5]
        self.assertEqual(bad, {})

    def test_files_without_a_batch_are_recipes_or_the_critic(self):
        extra = [n for n in self.files if n not in self.batches]
        self.assertEqual([n for n in extra if not (n.startswith("recipe_") or n == "zz_critic")], [])

    def test_app_and_kind_legal_and_match_the_file(self):
        bad = []
        for name, doc in self.files.items():
            for c in doc.get("cards") or []:
                app, kind = c.get("app"), c.get("kind")
                if name.startswith("recipe_"):
                    ok = kind == "recipe" and app in ("PS", "AI", "CDR", "multi")
                else:
                    ok = app in KINDS and kind in KINDS[app] and name.rsplit("_", 1)[0] == kind
                if not ok:
                    bad.append(f"{name}: {c.get('id')} app={app} kind={kind}")
        self.assertEqual(bad, [])

    def test_ids_unique_per_kind(self):
        seen = Counter((c.get("kind"), c.get("id")) for d in self.files.values() for c in d.get("cards") or [])
        self.assertEqual([k for k, n in seen.items() if n > 1], [])

    def test_vocabularies(self):
        bad = []
        for name, d in self.files.items():
            for c in d.get("cards") or []:
                v = (c.get("verified") or {}).get("verdict")
                if v is not None and v not in validate_cards.VERDICT:
                    bad.append(f"{name} {c.get('id')}: verdict {v!r}")
                if c.get("status") not in validate_cards.STATUS:
                    bad.append(f"{name} {c.get('id')}: status {c.get('status')!r}")
                if c.get("confidence") not in validate_cards.CONF:
                    bad.append(f"{name} {c.get('id')}: confidence {c.get('confidence')!r}")
        self.assertEqual(bad, [])

    def test_no_kind_has_more_cards_than_harvest_items(self):
        items = {d["kind"]: len(d["items"]) for d in (load_json(f) for f in (ROOT / "harvest").glob("*/*.json"))}
        cards = Counter(c.get("kind") for d in self.files.values() for c in d.get("cards") or [])
        self.assertEqual({k: n for k, n in cards.items() if k in items and n > items[k]}, {})

    def test_recipe_plans_pass_check_and_cite_real_cards(self):
        import pgd
        known = {c.get("id") for c in pgd.cards() if c.get("kind") != "recipe"}
        bad = []
        for name, doc in self.files.items():
            for r in (doc.get("cards") or []) if name.startswith("recipe_") else []:
                for app, plan in (r.get("plans") or {}).items():
                    bad += [f"{r['id']} {app}: {x}" for x in pgd.check_plan(plan)]
                bad += [f"{r['id']}: built_from {i!r} has no card" for i in r.get("built_from") or [] if i not in known]
        self.assertEqual(bad, [])

    def test_critic_shape(self):
        z = self.files.get("zz_critic")
        if z is None:
            self.skipTest("no completeness critic yet (the recipes stage writes it)")
        self.assertTrue({"gaps", "weak_cards", "doubtful", "next_steps"} & set(z))


if __name__ == "__main__":
    unittest.main()
