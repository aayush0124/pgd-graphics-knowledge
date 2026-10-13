"""PGD pipeline: one entry point for every stage.

    python pipeline.py status [--json | --markdown]   what is done, per stage and per app / kind (exit 0 / 10 / 1)
    python pipeline.py run <stage>                    run a deterministic stage; live / agent stages print how to run them
    python pipeline.py all                            every deterministic stage in order (check_harvest, batches,
                                                      skeleton, validate, sheets, docs)
    python pipeline.py doctor                         Python, apps, paths, free RAM

Exit codes: 0 ok, 1 failure, 10 needs attention (a stage is incomplete, or it needs a live app or an agent).
Live and agent stages never run from here (and never in CI): they drive Photoshop / Illustrator / CorelDRAW or need a
Claude Workflow run; `run <stage>` prints the exact workflow file and launch args instead.
Data comes from $PGD_HOME when set, else from this file's folder.
"""
import json, os, platform, shutil, subprocess, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path

CODE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("PGD_HOME") or CODE)
sys.path.insert(0, str(CODE))
import check_harvest, prepare_batches, validate_cards  # noqa: E402

KINDS = check_harvest.KINDS
VISUAL = prepare_batches.VISUAL
PRESET = {f"{a.lower()}_preset" for a in KINDS}
VERDICTS = ("pass", "weak", "wrong", "broken", "not_rendered")
TIER_ORDER = {"visual": 0, "tool": 1, "menu": 2, "preset": 3, "api": 4}
ARGS = '{"root": "<PGD folder>"%s}'
STAGES = [  # name, type, what runs it
    ("harvest", "live", "workflows/pgd_harvest.js (+ pgd_harvest_fix.js) driving tools/{ps,ai,cdr,api}/*; "
                        "args " + ARGS % ', "hostlock": "<hostlock.py>"'),
    ("check_harvest", "deterministic", "check_harvest.py"),
    ("batches", "deterministic", "prepare_batches.py -> work/batches/"),
    ("skeleton", "deterministic", "skeleton_cards.py -> cards/*_x*.json (API enum / library cards)"),
    ("cards", "agent", "workflows/pgd_cards.js; args " + ARGS % ', "batches": ["ps_filter_01", ...]'),
    ("validate", "deterministic", "validate_cards.py (every card file against its batch)"),
    ("galleries", "live", "workflows/pgd_preset_gallery.js and pgd_effect_gallery.js, one app per run "
                          "(tools/<app>/preset_gallery.py, effect_gallery.py); args " + ARGS % ', "app": "PS"'
                          + "; or pgd_app_chain.js for one app end to end"),
    ("sheets", "deterministic", "make_sheets.py --kind <app>_preset -> work/sheets/"),
    ("preset_cards", "agent", "workflows/pgd_preset_cards.js; args " + ARGS % ', "batches": ["ai_preset_18", ...]'),
    ("verify", "agent", "workflows/pgd_verify.js; args " + ARGS % ', "batches": ["ps_filter_01", ...]'),
    ("recipes", "agent", "workflows/pgd_recipes.js; args " + ARGS % ""),
    ("docs", "deterministic", "build_docs.py -> PGD.md, and the coverage block of README.md"),
]
ORDER = [s for s, t, _ in STAGES if t == "deterministic"]


def _load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 (missing or mid-write: treated as absent)
        return default


def _ranges(names):
    """['ai_preset_18', 'ai_preset_19', 'ai_preset_20', 'cdr_preset_02'] -> 'ai_preset_18..20, cdr_preset_02'"""
    out, run = [], []
    for n in sorted(names):
        k, _, i = n.rpartition("_")
        if run and run[-1][0] == k and i.isdigit() and int(i) == int(run[-1][1]) + 1:
            run.append((k, i))
            continue
        if run:
            out.append(run)
        run = [(k, i)]
    if run:
        out.append(run)
    return ", ".join(f"{r[0][0]}_{r[0][1]}" + (f"..{r[-1][1]}" if len(r) > 1 else "") for r in out)


def gather(home=HOME):
    """Everything status reports, as one dict (no app, no network)."""
    home = Path(home)
    harvest = {}
    errors = 0
    for f in sorted((home / "harvest").glob("*/*.json")):
        d = _load(f, {})
        err, _ = check_harvest.check_doc(d, f.name) if d else (["unreadable"], [])
        errors += len(err)
        if d:
            harvest[d["kind"]] = d
    plan = {n: b for d in harvest.values() for n, b in prepare_batches.plan(d)}
    disk = {p.stem for p in (home / "work" / "batches").glob("*.json")}
    card_files, cards, bad_files = {}, defaultdict(list), {}
    for cf in sorted((home / "cards").glob("*.json")):
        d = _load(cf)
        if d is None:
            bad_files[cf.name] = ["unreadable (mid-write?)"]
            continue
        card_files[cf.stem] = d.get("cards") or []
        for c in d.get("cards") or []:
            cards[c.get("kind")].append(c)
        b = plan.get(cf.stem)
        if b is not None:
            iss = validate_cards.check(b, d.get("cards") or [])
            if iss:
                bad_files[cf.name] = iss
    galleries = {}
    for g in sorted((home / "gallery").glob("*/")):
        idx = _load(g / "index.json", []) or []
        failed = _load(g / "failed.json", {}) or {}
        nr = (_load(g / "not_rendered.json", {}) or {}) | (_load(g / "not_renderable.json", {}) or {})
        # ref_* plates and <key>_1to1 detail crops (tools/cdr/effect_gallery.py) are not frames of their own
        frames = sum(1 for p in g.glob("*.png") if not p.name.startswith("ref") and not p.stem.endswith("_1to1"))
        galleries[g.name] = {"frames": frames, "index": len(idx), "failed": len(failed), "not_rendered": len(nr),
                             "accounted": len({x.get("id") for x in idx} | set(failed) | set(nr))}
    sheets = {p.name[:-len("_sheets.json")] for p in (home / "work" / "sheets").glob("*_sheets.json")}
    kinds = []
    for app, ks in KINDS.items():
        for k in sorted(ks, key=lambda x: (TIER_ORDER[prepare_batches.tier(x)], x)):
            bs = [n for n in plan if plan[n]["kind"] == k]
            vd = Counter((c.get("verified") or {}).get("verdict") for c in cards.get(k, []) if c.get("verified"))
            kinds.append({"app": app, "kind": k, "items": len((harvest.get(k) or {}).get("items") or []),
                          "batches": len(bs), "batches_on_disk": sum(n in disk for n in bs),
                          "card_files": sum(n in card_files for n in bs), "cards": len(cards.get(k, [])),
                          "verdicts": {v: vd.get(v, 0) for v in VERDICTS},
                          "frames": (galleries.get(k) or {}).get("frames", 0),
                          "sheets": sum(n in sheets for n in bs) if k in PRESET else None,
                          "missing_cards": sorted(n for n in bs if n not in card_files)})
    recipes = sorted(n for n in card_files if n.startswith("recipe_"))
    docs = home / "PGD.md"
    fresh = None
    if docs.exists():
        fresh = render_docs(home) == docs.read_text(encoding="utf-8")
    return {"home": str(home), "harvest_files": len(harvest), "harvest_kinds": sum(len(v) for v in KINDS.values()),
            "harvest_errors": errors, "batches": len(plan), "batches_on_disk": len(disk & set(plan)),
            "card_files": len(card_files), "cards": sum(len(v) for v in cards.values()), "bad_card_files": bad_files,
            "kinds": kinds, "galleries": galleries, "recipes": recipes,
            "critic": (home / "cards" / "zz_critic.json").exists(), "docs": "fresh" if fresh else
            ("stale" if fresh is False else "missing")}


def render_docs(home=HOME):
    """PGD.md as build_docs.py would write it now (built into a temp file; nothing in the repo is touched)."""
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / "PGD.md"
        subprocess.run([sys.executable, str(CODE / "build_docs.py"), str(out)], capture_output=True, check=True,
                       env=dict(os.environ, PGD_HOME=str(home)))
        return out.read_text(encoding="utf-8")


def stages(s):
    """[(stage, type, state, counts, how)]: state is done / partial / todo / FAIL."""
    K = s["kinds"]
    tot = lambda key, pick=lambda k: True: sum(k[key] for k in K if pick(k))  # noqa: E731
    std = lambda k: k["kind"] not in PRESET  # noqa: E731
    vis = lambda k: k["kind"] in VISUAL  # noqa: E731
    pre = lambda k: k["kind"] in PRESET  # noqa: E731
    judged = lambda pick: sum(sum(k["verdicts"].values()) for k in K if pick(k))  # noqa: E731
    gal_need = sorted(VISUAL | PRESET)
    gal_done = [g for g in gal_need if (s["galleries"].get(g) or {}).get("accounted", 0) >=
                max(1, next((k["cards"] or k["items"] for k in K if k["kind"] == g), 1))]
    rows = []

    def add(name, done, total, counts, fail=False):
        state = "FAIL" if fail else "done" if total and done >= total else "partial" if done else "todo"
        how = next(h for n, _, h in STAGES if n == name)
        rows.append((name, next(t for n, t, _ in STAGES if n == name), state, counts, how))

    add("harvest", s["harvest_files"], s["harvest_kinds"], f"{s['harvest_files']}/{s['harvest_kinds']} kinds, "
        f"{tot('items')} items")
    add("check_harvest", 1, 1, f"{s['harvest_errors']} errors", fail=s["harvest_errors"] > 0)
    add("batches", s["batches_on_disk"], s["batches"], f"{s['batches_on_disk']}/{s['batches']} batches in work/batches")
    x_missing = [n for k in K for n in k["missing_cards"] if "_x" in n]
    add("skeleton", 0 if x_missing else 1, 1, f"{len(x_missing)} API lookup batches without cards")
    add("cards", tot("card_files", std), tot("batches", std),
        f"{tot('card_files', std)}/{tot('batches', std)} non-preset batches carded, {tot('cards', std)} cards")
    nb = len(s["bad_card_files"])
    add("validate", s["card_files"] - nb, s["card_files"], f"{s['card_files'] - nb}/{s['card_files']} card files clean",
        fail=nb > 0)
    add("galleries", len(gal_done), len(gal_need), f"{len(gal_done)}/{len(gal_need)} galleries complete, "
        f"{sum(g['frames'] for g in s['galleries'].values())} frames")
    add("sheets", tot("sheets", pre), tot("batches", pre), f"{tot('sheets', pre)}/{tot('batches', pre)} preset batches")
    add("preset_cards", tot("card_files", pre), tot("batches", pre),
        f"{tot('card_files', pre)}/{tot('batches', pre)} preset batches carded, {tot('cards', pre)} cards")
    add("verify", judged(lambda k: vis(k) or pre(k)), tot("items", lambda k: vis(k) or pre(k)),
        f"{judged(vis)}/{tot('items', vis)} visual and {judged(pre)}/{tot('items', pre)} preset items have a verdict")
    add("recipes", len(s["recipes"]), 1, f"{len(s['recipes'])} recipe files, critic {'yes' if s['critic'] else 'no'}")
    add("docs", 1 if s["docs"] == "fresh" else 0, 1, f"PGD.md {s['docs']}")
    return rows


def kind_table(s):
    head = ["app", "kind", "items", "batches", "card files", "cards"] + list(VERDICTS) + ["frames", "sheets"]
    rows = [[k["app"], k["kind"], k["items"], k["batches"], k["card_files"], k["cards"]]
            + [k["verdicts"][v] for v in VERDICTS] + [k["frames"], "" if k["sheets"] is None else k["sheets"]]
            for k in s["kinds"]]
    return head, rows


def markdown(s):
    out = ["| stage | type | state | counts |", "|---|---|---|---|"]
    out += [f"| {n} | {t} | {st} | {c} |" for n, t, st, c, _ in stages(s)]
    head, rows = kind_table(s)
    out += ["", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    miss = [n for k in s["kinds"] if k["kind"] in PRESET for n in k["missing_cards"]]
    out += ["", f"Preset batches still without cards: {_ranges(miss) or 'none'}."]
    return "\n".join(out)


def status(argv):
    s = gather()
    rows = stages(s)
    if "--json" in argv:
        print(json.dumps(dict(s, stages=[dict(zip(("stage", "type", "state", "counts", "how"), r)) for r in rows]),
                         indent=1, ensure_ascii=False))
    elif "--markdown" in argv:
        print(markdown(s))
    else:
        print(f"PGD status ({s['home']})\n")
        w = max(len(r[0]) for r in rows)
        for n, t, st, c, how in rows:
            print(f"  {n:<{w}}  {t:<13}  {st:<7}  {c}")
        head, krows = kind_table(s)
        widths = [max(len(str(x)) for x in col) for col in zip(head, *krows)]
        print()
        for r in [head] + krows:
            print("  " + "  ".join(f"{str(x):>{wd}}" if i > 1 else f"{str(x):<{wd}}" for i, (x, wd) in
                                    enumerate(zip(r, widths))))
        miss = [n for k in s["kinds"] if k["kind"] in PRESET for n in k["missing_cards"]]
        print(f"\n  preset batches without cards ({len(miss)}): {_ranges(miss) or 'none'}")
        for f, iss in list(s["bad_card_files"].items())[:10]:
            print(f"  card file {f}: {len(iss)} issues, e.g. {iss[0]}")
    if any(st == "FAIL" for _, _, st, _, _ in rows):
        return 1
    return 0 if all(st == "done" for _, _, st, _, _ in rows) else 10


def _py(*a):
    return subprocess.run([sys.executable, *map(str, a)], cwd=HOME, env=dict(os.environ, PGD_HOME=str(HOME))).returncode


def readme_block(home=HOME):
    """Rewrite the coverage block of README.md (between the coverage markers) from status."""
    p = CODE / "README.md"
    if not p.exists():
        return 0
    t = p.read_text(encoding="utf-8")
    a, b = "<!-- coverage:start -->", "<!-- coverage:end -->"
    if a not in t or b not in t:
        return 0
    new = t[:t.index(a) + len(a)] + "\n" + markdown(gather(home)) + "\n" + t[t.index(b):]
    if new != t:
        p.write_text(new, encoding="utf-8", newline="\n")
    return 0


def run(stage):
    kinds = {n: t for n, t, _ in STAGES}
    if stage not in kinds:
        print(f"unknown stage {stage!r}; stages: {', '.join(kinds)}")
        return 1
    if kinds[stage] != "deterministic":
        how = next(h for n, _, h in STAGES if n == stage)
        print(f"{stage} needs {'a live app' if kinds[stage] == 'live' else 'an agent run'} and is never run from "
              f"pipeline.py. Run it with: {how}")
        return 10
    if stage == "check_harvest":
        return _py(CODE / "check_harvest.py")
    if stage == "batches":
        return _py(CODE / "prepare_batches.py")
    if stage == "skeleton":
        return _py(CODE / "skeleton_cards.py")
    if stage == "validate":
        return _py(CODE / "validate_cards.py")
    if stage == "sheets":
        try:
            import PIL  # noqa: F401
        except ImportError:
            print("sheets need Pillow (pip install pillow)")
            return 10
        rc = 0
        for k in sorted(PRESET):
            if (HOME / "gallery" / k / "index.json").exists():
                rc = max(rc, _py(CODE / "make_sheets.py", "--kind", k))
            else:
                print(f"{k}: no gallery/{k}/index.json yet (run the preset gallery first)")
                rc = max(rc, 10)
        return rc
    if stage == "docs":
        return _py(CODE / "build_docs.py") or readme_block()
    return 1


def doctor():
    ok = sys.version_info >= (3, 12)
    print(f"python {platform.python_version()} ({'ok' if ok else 'need 3.12+'}) on {platform.system()} {platform.release()}")
    print(f"PGD_HOME {HOME}{' (from env)' if os.environ.get('PGD_HOME') else ''}")
    for d in ("harvest", "cards", "work", "gallery", "media", "tools", "workflows"):
        p = HOME / d
        print(f"  {d:<10} {'present' if p.exists() else 'missing'}")
        ok &= p.exists() or d in ("work", "gallery")
    apps = {"Photoshop 2026": os.environ.get("PGD_PS_EXE") or r"C:\Program Files\Adobe\Adobe Photoshop 2026\Photoshop.exe",
            "Illustrator 2026": os.environ.get("PGD_AI_EXE") or r"C:\Program Files\Adobe\Adobe Illustrator 2026\Support Files"
                                                               r"\Contents\Windows\Illustrator.exe",
            "CorelDRAW 2024": str(Path(os.environ.get("PGD_CDR_DIR") or r"C:\Program Files\Corel\CorelDRAW Graphics "
                                                                        r"Suite\25\Programs64") / "CorelDRW.exe")}
    found = {a: Path(p).exists() for a, p in apps.items()}
    for a, p in apps.items():
        print(f"  {a:<17} {'found' if found[a] else 'not found'}: {p}")
    for mod in ("PIL", "win32com", "uiautomation", "psutil"):
        try:
            __import__(mod)
            print(f"  module {mod:<12} ok")
        except ImportError:
            print(f"  module {mod:<12} missing ({'live stages only' if mod != 'PIL' else 'sheets stage'})")
    print(f"  node {'ok' if shutil.which('node') else 'missing (workflow syntax tests skip)'}")
    hl = CODE / "tools" / "hostlock.py"
    print("  hostlock " + ("tools/hostlock.py (named mutex Global\\aisys_host_<slot>)" if hl.exists() else "MISSING"))
    ram = free_ram_mb()
    print(f"  free RAM {ram if ram is not None else '?'} MB")
    if not ok:
        return 1
    return 0 if all(found.values()) else 10


def free_ram_mb():
    if os.name == "nt":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                       [(n, ctypes.c_ulonglong) for n in ("total", "avail", "ptot", "pavail", "vtot", "vavail", "x")]
        m = MS()
        m.len = ctypes.sizeof(MS)
        return m.avail // 2**20 if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)) else None
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) // 1024
    except OSError:
        return None


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("stages:\n" + "\n".join(f"  {n:<14} {t:<13} {h}" for n, t, h in STAGES))
        return 0
    cmd = argv[0]
    if cmd == "status":
        return status(argv[1:])
    if cmd == "run" and len(argv) == 2:
        return run(argv[1])
    if cmd == "all":
        for st in ORDER:
            print(f"== {st}", flush=True)
            rc = run(st)
            if rc == 1:
                return 1
        return status([])
    if cmd == "doctor":
        return doctor()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
