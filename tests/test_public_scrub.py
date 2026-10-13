"""Public-scrub gate: nothing that is (or would be) tracked may carry machine paths, client / employer / episode names,
personal data, credentials, vendor-owned files, binaries, files over 5 MB, or long verbatim vendor documentation.

Scope: `git ls-files --cached --others --exclude-standard` (tracked + would be added); a plain walk when git is absent.

Two tiers:
- code, docs, harvest, tests, workflows: any hit fails, always.
- cards/*.json (written by agents): hits are reported, and the test SKIPS with the count, unless strict mode is on:
  PGD_SCRUB_STRICT=1 makes card hits fail too. CI runs strict, so the public repo can only be pushed once the cards are
  clean. Before publishing, run strict locally:  PGD_SCRUB_STRICT=1 python -m unittest tests.test_public_scrub -v
  The hit list for fixing: python tests/test_public_scrub.py --cards-report hits.json
  (each hit: file, card id, field, offending text, proposed replacement).

Names are matched as whole words against salted-free sha256 prefixes, so this public file does not spell them out.
The owner's first name may appear only directly followed by his surname (the LICENSE / README credit).
"""
import bisect, hashlib, json, os, re, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 5 * 2**20
MAX_WORDS = 25
SEP = r"[\\/]+"
MACHINE = re.compile("|".join([
    r"[A-Za-z]:" + SEP + "Users" + SEP + r"(?![<%$]|Public\b|Default\b)[^\\/\s\"'<>]+",  # a user's home folder
    r"[A-Za-z]:" + SEP + "AI_" + "Systems_", r"D:" + SEP + "NW" + "N_", r"D:" + SEP + "My_" + "Work_",
    "AppData" + SEP + "Local" + SEP + "Temp", "scratch" + "pad", r"C--" + "Users-",
]), re.I)
NAME_HASHES = {"c9c61db58193", "1c2d1d71cee2", "9402bbacd280", "8b719d108e8a", "44c8cf4ce061", "0a16bea95629",
               "e75eb6e2d3fb", "89b0a936bc78"}  # client / employer / episode names and the machine's user name
FIRST_NAME, SURNAME = "00d8aec08899", "216c8c0df560"  # the owner: his first name only as "<first> <surname>" (credit)
NAME_START = re.compile(r"(?<![a-z0-9])(?:aa|bj|mo|nc|sa|su|ta)[a-z0-9]*")  # first letters of the hashed words
NEXT_WORD = re.compile(r"\s+([a-z]+)")
EPISODE = re.compile(r"\bepisodes[\\/]+\w", re.I)
EMAIL = re.compile(r"@(?:gmail|googlemail|yahoo|outlook|hotmail|live|icloud|proton|protonmail|rediffmail)\.[a-z.]+", re.I)
PHONE = re.compile(r"(?<![\w.#-])\+91[\s-]?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_VAL = r"[\"']?\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']"
# credentials: (needle, pattern starting with that literal, run on the lower-cased text?). One literal-led pattern
# per needle is many times faster than one alternation over megabytes of harvest JSON.
SECRETS = [(n, re.compile(p), low) for n, p, low in (
    ("sk-", r"sk-(?:ant-)?[A-Za-z0-9_-]{24,}", False), ("ghp_", r"ghp_[A-Za-z0-9]{30,}", False),
    ("github_pat_", r"github_pat_\w{30,}", False), ("AKIA", r"AKIA[0-9A-Z]{16}(?![0-9A-Z])", False),
    ("xox", r"xox[abposr]-[A-Za-z0-9-]{10,}", False), ("-----BEGIN", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", False),
    ("AIza", r"AIza[0-9A-Za-z_-]{35}", False), ("api", r"api[_-]?key" + _VAL, True), ("secret", "secret" + _VAL, True),
    ("passw", r"passw(?:or)?d" + _VAL, True), ("auth", r"auth[_-]?token" + _VAL, True), ("bearer", "bearer" + _VAL, True))]
VENDOR_EXT = {".ffx", ".mogrt", ".cube", ".look", ".prfpset", ".abr", ".atn", ".grd", ".pat", ".asl", ".csh", ".aia",
              ".aep", ".prproj", ".psd", ".ai", ".cdr", ".exe", ".dll", ".msi", ".8bf", ".aip", ".tlb", ".pyc", ".zip"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".mp4", ".mov", ".wav", ".mp3"}
TEXT_EXT = {".py", ".js", ".jsx", ".json", ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".svg", ".gitignore", ""}


def tracked(root=ROOT):
    """Relative paths of every file that is or would be tracked."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root,
                             capture_output=True, check=True).stdout.decode("utf-8")
        files = sorted({f for f in out.split("\0") if f})
        return [f for f in files if (root / f).exists()]
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", "gallery", "work", "__pycache__"}
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                      if p.is_file() and not skip & set(p.relative_to(root).parts))


def _h(w):
    return hashlib.sha256(w.encode()).hexdigest()[:12]


def name_hits(text):
    return sorted(w for w in set(NAME_START.findall(text.lower())) if _h(w) in NAME_HASHES or _h(w) == FIRST_NAME)


RULES = (("machine path", MACHINE), ("episode path", EPISODE), ("phone number", PHONE))
NEEDLES = {  # a rule's regex only runs when one of its (lower-case) needles is in the text: substring search is cheap
    "machine path": ("users", "ai_" "systems_", "nw" "n_", "my_" "work_", "appdata", "scratch" "pad"),
    "episode path": ("episodes",), "phone number": ("+91",),
}
LOCAL = re.compile(r"[\w.+-]+$")


def spans(text):
    """[(rule, start, end)] for one text."""
    low = text.lower()
    out = [(rule, m.start(), m.end()) for rule, rx in RULES if any(n in low for n in NEEDLES[rule])
           for m in rx.finditer(text)]
    for needle, rx, on_low in SECRETS:
        t = low if on_low else text
        if needle in t:
            out += [("credential", m.start(), m.end()) for m in rx.finditer(t)
                    if not (m.start() and (t[m.start() - 1].isalnum() or t[m.start() - 1] == "_"))]
    if "@" in text:  # match the domain from the "@", then take the local part to its left
        for m in EMAIL.finditer(text):
            loc = LOCAL.search(text, max(0, m.start() - 64), m.start())
            if loc:
                out.append(("personal email", loc.start(), m.end()))
    for w in name_hits(text):
        first = _h(w) == FIRST_NAME
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low):
            if first:
                nxt = NEXT_WORD.match(low, m.end())
                if nxt and _h(nxt.group(1)) == SURNAME:
                    continue  # the full-name credit (LICENSE, README)
            out.append(("bare first name" if first else "name", m.start(), m.end()))
    return out


def text_hits(text):
    """[(rule, excerpt)] for one text."""
    return [(r, text[max(0, a - 40):b + 40]) for r, a, b in spans(text)]


def long_vendor_text(doc):
    """vendor API description strings over MAX_WORDS words in one harvest document."""
    out = []

    def walk(o, key):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, str) and key == "description" and len(o.replace("[...]", "").split()) > MAX_WORDS:
            out.append(o[:120])
    if str(doc.get("kind", "")).endswith("_api"):
        walk(doc.get("items"), "")
    return out


def truncated_prefixes(root=ROOT):
    """First 20 words of every vendor description the harvest keeps only in part (it ends in "[...]")."""
    pre = set()
    for f in (root / "harvest").glob("*/*_api.json"):
        def walk(o, key):
            if isinstance(o, dict):
                for k, v in o.items():
                    walk(v, k)
            elif isinstance(o, list):
                for v in o:
                    walk(v, key)
            elif isinstance(o, str) and key == "description" and o.endswith("[...]"):
                pre.add(" ".join(o.split()[:20]))
        walk(json.loads(f.read_text(encoding="utf-8")), "")
    return pre


def propose(rule, s):
    if rule == "machine path" or rule == "name" and MACHINE.search(s):
        s2 = re.sub(r"[A-Za-z]:" + SEP + "AI_" + r"Systems_[\\/]+PGD[\\/]+", "", s)
        s2 = re.sub(r"[A-Za-z]:([\\/])+Users\1+[^\\/\s\"'<>]+", "%USERPROFILE%", s2)
        return s2
    if rule == "verbatim vendor text":
        return " ".join(s.split()[:MAX_WORDS]) + " [...]"
    return "REVIEW: remove or generalise (" + rule + ")"


def card_hits(root=ROOT, files=None):
    """[{file, id, field, rule, text, proposed}] for card files."""
    pre = truncated_prefixes(root)
    out = []
    for rel in files if files is not None else [f for f in tracked(root) if f.startswith("cards/")]:
        try:
            raw = (root / rel).read_text(encoding="utf-8")
            doc = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            out.append({"file": rel, "id": None, "field": None, "rule": "unreadable", "text": str(e), "proposed": ""})
            continue
        cards = doc.get("cards") if isinstance(doc, dict) else None
        units = [(c.get("id"), c) for c in cards] if isinstance(cards, list) else [(None, doc)]
        strings = []  # (card id, field, text)

        def walk(o, field, cid):
            if isinstance(o, dict):
                for k, v in o.items():
                    walk(v, f"{field}.{k}" if field else k, cid)
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    walk(v, f"{field}[{i}]", cid)
            elif isinstance(o, str):
                strings.append((cid, field, o))
        for cid, c in units:
            walk(c, "", cid)
        # one regex pass over all strings of the file, mapped back to the string each hit starts in
        starts, pos = [], 0
        for _, _, s in strings:
            starts.append(pos)
            pos += len(s) + 1
        rules = {}
        for r, a, _ in spans("\n".join(s for _, _, s in strings)):
            rules.setdefault(bisect.bisect_right(starts, a) - 1, set()).add(r)
        if "_api" in rel and pre:
            for i, (_, _, s) in enumerate(strings):
                words = s.split()
                if len(words) > MAX_WORDS and any(p in " ".join(words) for p in pre):
                    rules.setdefault(i, set()).add("verbatim vendor text")
        for i in sorted(rules):
            cid, field, s = strings[i]
            out += [{"file": rel, "id": cid, "field": field, "rule": r, "text": s, "proposed": propose(r, s)}
                    for r in sorted(rules[i])]
    return out


class PublicScrub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = tracked()

    def test_scope_is_not_empty(self):
        self.assertTrue(any(f == "pgd.py" for f in self.files), "pgd.py should be in the tracked set")
        for d in ("gallery/", "work/"):
            self.assertFalse([f for f in self.files if f.startswith(d)], f"{d} must stay untracked")

    def test_no_vendor_binary_or_large_files(self):
        bad, samples = [], 0
        for f in self.files:
            p, ext = ROOT / f, Path(f).suffix.lower()
            size = p.stat().st_size
            if f.startswith("docs/samples/"):
                samples += size
            if ext in VENDOR_EXT:
                bad.append(f"{f}: vendor / binary file type {ext}")
            if ext in IMAGE_EXT and not f.startswith("docs/samples/"):
                bad.append(f"{f}: media outside docs/samples/")
            if size > MAX_BYTES:
                bad.append(f"{f}: {size / 2**20:.1f} MB (limit 5 MB)")
        if samples > MAX_BYTES:
            bad.append(f"docs/samples/ holds {samples / 2**20:.1f} MB (limit 5 MB)")
        self.assertEqual(bad, [])

    def test_code_docs_harvest_clean(self):
        bad = []
        for f in self.files:
            if f.startswith("cards/") or Path(f).suffix.lower() not in TEXT_EXT:
                continue
            text = (ROOT / f).read_text(encoding="utf-8", errors="replace")
            bad += [f"{f}: {r}: ...{x}..." for r, x in text_hits(text)]
            if f.startswith("harvest/") and f.endswith("_api.json"):
                bad += [f"{f}: vendor description over {MAX_WORDS} words: {x}" for x in long_vendor_text(json.loads(text))]
        self.assertEqual(bad, [], "\n" + "\n".join(bad[:60]))

    def test_cards_clean(self):
        hits = card_hits(files=[f for f in self.files if f.startswith("cards/")])
        if not hits:
            return
        by = {}
        for h in hits:
            by[h["rule"]] = by.get(h["rule"], 0) + 1
        msg = f"{len(hits)} card hits {by}; list them: python tests/test_public_scrub.py --cards-report hits.json"
        if os.environ.get("PGD_SCRUB_STRICT") == "1":
            self.fail(msg + "\n" + "\n".join(f"{h['file']} {h['id']} {h['field']}: {h['rule']}" for h in hits[:40]))
        self.skipTest(msg + " (strict mode PGD_SCRUB_STRICT=1 fails on them)")

    def test_rules_catch_what_they_should(self):  # negative tests for the scrubber itself
        home = "C:" + "\\Users\\" + "someone\\Desktop\\x.png"
        for s, rule in ((home, "machine path"), ("E:/" + "AI_" + "Systems_/x", "machine path"),
                        ("mail me: someone@" + "gm" + "ail.com", "personal email"), ("ghp_" + "a" * 36, "credential"),
                        ('{"api_key": "' + "q" * 20 + '"}', "credential"), ("call +91 98" + "765 43210", "phone number"),
                        ("see episodes/" + "ep01/spec.json", "episode path")):
            self.assertIn(rule, {r for r, _ in text_hits(s)}, s)
        self.assertEqual(text_hits("C:/Users/<you>/Documents and %USERPROFILE%\\AppData, Program Files"), [])
        self.assertEqual(text_hits("Modifier keys; Gaussian Blur radius 12 px; 1234567890"), [])
        self.assertEqual(propose("machine path", "E:/" + "AI_" + "Systems_/PGD/gallery/ai_effect/x.png"),
                         "gallery/ai_effect/x.png")
        first, full = "Aay" + "ush", "Aay" + "ush Pali" + "wal"
        for s in (f"{first} said so", f"{first}'s page", f"ask {first.lower()}\n{full}"):
            self.assertIn("bare first name", {r for r, _ in text_hits(s)}, s)
        self.assertEqual(text_hits(f"Copyright (c) 2026 {full}; credit \"PGD by {full}\""), [])


if __name__ == "__main__":
    if sys.argv[1:2] == ["--cards-report"]:
        hits = card_hits()
        Path(sys.argv[2]).write_text(json.dumps(hits, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{len(hits)} card hits -> {sys.argv[2]}")
    else:
        unittest.main()
