"""PGD plan runner: run a recipe's app plan step by step in the live app, on a known input document, and record what
every step did. pgd.py check proves a plan is well formed; this proves what it does when it runs.

    python run_plan.py list [APP]                          every plan: steps with a route / manual, last run, verdict
    python run_plan.py show <recipe> [APP]                 the compiled steps (offline: what each step will send)
    python run_plan.py run <recipe | family | all | a,b,...> [APP ...] [--force] [--no-record]
                                                           run in Photoshop / Illustrator / CorelDRAW; resumable: a
                                                           plan whose recorded run matches it is skipped (--force);
                                                           exit 1 when a plan failed or crashed
    python run_plan.py strip <recipe | family> APP         rebuild the step strips from the saved step frames
    python run_plan.py get <recipe> APP [plan.json]        the plan alone, to edit (written to plan.json as UTF-8, or
                                                           printed: a PowerShell redirect re-encodes it, use the file)
    python run_plan.py put <recipe> APP plan.json          save an edited plan (pgd.py check, with the plan's default
                                                           input, and a compile pass must accept it)
    python run_plan.py judge <recipe> APP --verdict pass|weak|wrong|broken --note "..." --by "..."
                                                           the judge's verdict on the current recorded run
    python run_plan.py judge <recipe> APP --second "agree" | "corrected: ..." [--verdict ...]
                                                           an independent second opinion on that verdict
Every card write takes work/plans/cards.lock (an OS lock on the file), so runs and edits for several apps can go on at
once. App codes may be written in any case. Exit codes: 0 ok, 1 a plan failed / was not saved, 2 usage error.

<recipe> is a recipe id (recipe:text_effects:neon_glow), its key (text_effects.neon_glow) or its exact name; get, put
and judge take exactly one recipe (a family, 'all' or a comma list is refused). Each app backend
(tools/<app>/plan_<app>.py) starts its own app and never sends a script to one another client started.

Plan format (pgd.py check_plan validates it): {"app": "PS", "input": {...}, "steps": [step, ...]}.
  input  the document the plan starts from (INPUTS): {"plate": "photo"} | {"plate": "text", "text": "NEON",
         "background": "#141414", "color": "#E1E1E1"} | {"plate": "vector"} | {"plate": "blank"}. "text" on any plate
         adds a type layer / text object (label "type"; "at": [x, y] its centre in px, "size" px, "color", "font").
         "damage" on the photo plate gives clean-up recipes something to fix (DAMAGE: noise, dust, scratches, jpeg,
         blur, haze, tilt), e.g. {"plate": "photo", "damage": {"noise": 12, "dust": 80}}: synthetic, reproducible.
         Left out: the family default (default_input). Each plate names its layers / objects as labels (LABELS).
  step   {"kind", "id" | "name", "settings", "effects", "note"} as before, plus
           "target": a label: the layer / object the step acts on (else the active one)
           "as":     label the layer / object that is active after the step, for a later "target"
           "script": app-native code run instead of the item's own route (ExtendScript for PS / AI with d = the
                     document and L = the target; Python for CDR with app, doc, s = the target shape). Required for
                     api / tool steps and for menu commands whose route needs values (Image Size, Canvas Size ...).
           "labels": the labels a script step adds itself (CDR labels['bar'] = shape), for later targets
         A script that writes a file (a PDF, a texture) writes it into OUT (PS / AI: a path string; CDR: `out`), the
         plan run's own folder work/plans/out/<key>/<APP>/, and nowhere else.
         A step with no route is run as "manual": skipped, reported, and the run goes on without it.
Output: gallery/recipes/<APP>/<key>.png (960x540, the document at the end), <key>_steps.png (the input and the
document after every step; transparency over a mid-grey checker in both), <key>_1to1.png (the DETAIL region at the
document's own pixels, for sharpening / noise / upscale), and the plan's "run" record in its recipe card:
  {"date", "app_version", "input", "plan_hash", "result", "steps": [{"step", "status", "note"}], "layers", "frame",
   "strip"}
  result: complete (every step ran) | partial (some manual, or a PS / AI step ran without settings it could not send
          ("unsent"); none failed) | failed (a step errored) | manual (none ran)
A judge then writes "verified" ({"verdict", "note", "date", "by", "plan_hash"}) from the frame and strip against the
recipe's summary: pass | weak | wrong | broken. Both carry the plan_hash of the plan's runnable content (notes left
out): a plan whose input, steps, settings, targets or scripts change no longer matches them; a corrected note does.
A new run moves the verdict on the run before it to "verified_history": a verdict never outlives the run it judged.
"""
import argparse, hashlib, importlib.util, json, os, re, sys, tempfile, time
from pathlib import Path

CODE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("PGD_HOME") or CODE)
sys.path.insert(0, str(CODE))
import pgd  # noqa: E402

APPS = pgd.APPS
OUT = HOME / "gallery" / "recipes"
INPUTS = {"photo": "media/plate_photo.png, 1920x1080",
          "text": "1920x1080, background (default mid grey #808080) + one type layer / text object (default 'PGD', "
                  "Arial Black 360 px, #E1E1E1, centred)",
          "vector": "media/plate_vector.svg: orange_box, blue_star, grad_circle, pgd_type (live type), zigzag",
          "blank": "1920x1080 white page"}
LABELS = pgd.INPUT_LABELS  # + "type" when the input has "text"; "art" (the whole vector plate) is Illustrator's only
STRIP_CELL, STRIP_COLS, FRAME = (320, 180), 4, (960, 540)
# the 1:1 detail crop <key>_1to1.png: x, y, w, h on the 1920x1080 frame (the galleries' CROP_BOX: the photo's lower
# right, the colour bars, grey ramp and hairlines), scaled to the document's own size, so sharpening, noise and an
# upscale can be judged at their real pixels
DETAIL = (1408, 568, 512, 512)
UNTRACKED = ("run", "verified", "verified_history")  # plan keys that record a run, not part of what runs
VERDICTS = ("pass", "weak", "wrong", "broken")


def default_input(recipe, app):
    fam = recipe.get("family")
    if fam == "text_effects":
        return {"plate": "text"}
    if fam == "vector_illustration" or fam == "print_prep" and app != "PS":
        return {"plate": "vector"}
    return {"plate": "photo"}


def plan_input(recipe, app):
    return recipe["plans"][app].get("input") or default_input(recipe, app)


# what each kind of damage does (pgd.INPUT_DAMAGE holds the ranges pgd.py check enforces)
DAMAGE = {"noise": "Gaussian noise, sigma in 0-255 levels (8-20 shows)",
          "dust": "number of dust specks and hairs, dark and light, radius 1-4 px",
          "scratches": "number of thin light scratches",
          "jpeg": "re-saved as JPEG at this quality (5-20 gives 8x8 blocking and ringing)",
          "blur": "Gaussian blur radius in px (a soft picture for sharpening)",
          "haze": "0-1: blended toward light grey (a washed-out picture)",
          "tilt": "degrees, rotated and scaled to fill the frame (counter-clockwise when positive)"}


def damaged_photo(damage):
    """media/plate_photo.png with synthetic, reproducible damage (seeded by the settings) for clean-up recipes ->
    work/plans/plates/photo_<hash>.png (built once)"""
    import io, math, random
    from PIL import Image, ImageDraw, ImageFilter
    key = hashlib.sha1(json.dumps(damage, sort_keys=True).encode()).hexdigest()[:10]
    out = HOME / "work" / "plans" / "plates" / f"photo_{key}.png"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(HOME / "media" / "plate_photo.png").convert("RGB")
    rnd = random.Random(key)
    if damage.get("haze"):
        im = Image.blend(im, Image.new("RGB", im.size, (200, 200, 200)), float(damage["haze"]))
    if damage.get("blur"):
        im = im.filter(ImageFilter.GaussianBlur(float(damage["blur"])))
    if damage.get("tilt"):
        a = float(damage["tilt"])
        r = math.radians(abs(a))
        k = math.cos(r) + im.width / im.height * math.sin(r)  # the scale that keeps the corners covered
        big = im.resize((int(im.width * k) + 2, int(im.height * k) + 2), Image.BICUBIC).rotate(a, Image.BICUBIC)
        x, y = (big.width - im.width) // 2, (big.height - im.height) // 2
        im = big.crop((x, y, x + im.width, y + im.height))
    if damage.get("noise"):
        import numpy as np
        px = np.asarray(im, dtype=np.float32)
        px = px + np.random.default_rng(int(key, 16) % 2 ** 32).normal(0, float(damage["noise"]), px.shape)
        im = Image.fromarray(np.clip(px, 0, 255).astype("uint8"))
    d = ImageDraw.Draw(im)
    for _ in range(int(damage.get("dust") or 0)):
        x, y, rad = rnd.randrange(im.width), rnd.randrange(im.height), rnd.choice((1, 1, 2, 2, 3, 4))
        c = rnd.choice(((20, 20, 20), (235, 235, 230)))
        if rnd.random() < 0.2:  # a hair
            d.line([(x, y), (x + rnd.randint(-30, 30), y + rnd.randint(-30, 30))], fill=c, width=1)
        else:
            d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=c)
    for _ in range(int(damage.get("scratches") or 0)):
        x = rnd.randrange(im.width)
        d.line([(x, 0), (x + rnd.randint(-80, 80), im.height)], fill=(225, 225, 220), width=1)
    if damage.get("jpeg"):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=int(damage["jpeg"]))
        im = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    im.save(out)
    return out


def open_input(sess, inp):
    """open the plan's input in the app; a "damage" input hands the backend the damaged photo as _photo (never
    recorded: the run records the input as the plan states it)"""
    if inp.get("damage"):
        return sess.open(dict(inp, _photo=str(damaged_photo(inp["damage"]))))
    return sess.open(inp)


def _runnable(x):
    """the plan without its notes (prose fixed after a run does not change what runs, so it keeps run and verdict)"""
    if isinstance(x, dict):
        return {k: _runnable(v) for k, v in x.items() if k != "note" and k not in UNTRACKED}
    if isinstance(x, list):
        return [_runnable(v) for v in x]
    return x


def plan_hash(plan):
    """what a run record and a verdict are tied to: the plan's runnable content (input, steps, settings, targets,
    scripts), not its notes"""
    core = _runnable(plan)
    return hashlib.sha1(json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _legacy_hash(plan):
    """plan_hash before 2026-10-15 evening (notes included); only for migrating old records"""
    core = {k: v for k, v in plan.items() if k not in UNTRACKED}
    return hashlib.sha1(json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def rkey(recipe):
    """recipe:text_effects:neon_glow -> text_effects.neon_glow"""
    return ".".join(recipe["id"].split(":")[1:])


def recipes():
    """every recipe card; a missing cards/ or harvest/ folder or an unreadable card or harvest file is a usage error
    (exit 2), never a silently shorter list or a plan whose lost steps compile as manual"""
    bad = pgd.unreadable() + [d + "/" for d in ("cards", "harvest") if not (HOME / d).is_dir()]
    if bad:
        _usage(f"{', '.join(bad)} unreadable or missing in PGD_HOME {HOME}")
    return [c for c in pgd.cards() if c.get("kind") == "recipe"]


def _usage(msg):
    """a usage error: the message on stderr, exit 2"""
    print(f"run_plan.py: {msg}", file=sys.stderr)
    raise SystemExit(2)


def select(what):
    """a recipe id / key / exact name, a family, 'all', or a comma list of those -> [recipe]. An exact id, key or name
    is matched first (six recipe names hold a comma)."""
    rs = recipes()
    if what == "all":
        return rs
    hit = [r for r in rs if what in (r["id"], rkey(r), r["name"])]
    if hit:
        return hit
    if "," in what:  # several keys / families in one run (one app session)
        return [r for w in what.split(",") if w.strip() for r in select(w.strip())]
    hit = [r for r in rs if r.get("family") == what]
    if not hit:
        _usage(f"no recipe or family {what!r} (python run_plan.py list)")
    return hit


def select_one(what, app=None):
    """exactly one recipe by id, key or exact name (get / put / judge read or write ONE plan); with app, it must have
    a plan for that app"""
    hit = [r for r in recipes() if what in (r["id"], rkey(r), r["name"])]
    if len(hit) != 1:
        fam = [rkey(r) for r in recipes() if r.get("family") == what]
        _usage(f"{what!r} names {len(hit)} recipes; give one recipe id, key or exact name"
               + (f" (family {what}: {', '.join(fam)})" if fam else " (python run_plan.py list)"))
    if app and app not in hit[0]["plans"]:
        _usage(f"{hit[0]['id']} has no {app} plan (it has {', '.join(sorted(hit[0]['plans']))})")
    return hit[0]


_BACKENDS = {}


def backend(app):
    """tools/<app>/plan_<app>.py, loaded under a unique module name (each app folder has same-named modules)"""
    if app not in _BACKENDS:
        p = CODE / "tools" / app.lower() / f"plan_{app.lower()}.py"
        spec = importlib.util.spec_from_file_location(f"pgd_plan_{app.lower()}", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _BACKENDS[app] = m
    return _BACKENDS[app]


def compile_plan(recipe, app):
    """-> [compiled step]: {"step", "kind", "label", "target", "as", "op"}; op None with "manual" set when the step
    has no route, or "error" set when the plan itself is wrong (the backend says why)."""
    plan = recipe["plans"][app]
    inp = plan_input(recipe, app)
    if inp.get("plate") not in INPUTS:
        raise ValueError(f"{recipe['id']} {app}: input plate {inp.get('plate')!r} is not one of {sorted(INPUTS)}")
    return backend(app).compile_steps(plan, inp)


class _Lock:
    """one writer of the recipe card files at a time across processes (runs and edits for several apps go on at
    once): an OS lock on the first byte of work/plans/cards.lock (msvcrt on Windows, flock elsewhere). The OS drops it
    when its holder exits or dies, so there is no stale lock to take over, and the file itself is never removed."""
    path = HOME / "work" / "plans" / "cards.lock"

    def _os_lock(self, on):
        if os.name == "nt":
            import msvcrt
            self.f.seek(0)
            msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK if on else msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.f.fileno(), (fcntl.LOCK_EX | fcntl.LOCK_NB) if on else fcntl.LOCK_UN)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a+b")
        t0 = time.time()
        while True:
            try:
                self._os_lock(True)
                return self
            except OSError:
                if time.time() - t0 > 300:
                    self.f.close()
                    raise TimeoutError(f"{self.path} held for 5 min")
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            self._os_lock(False)
        finally:
            self.f.close()


def update_plan(recipe_id, app, fn):
    """fn(plan) edits plans[app] in place: under the lock, on a fresh read of the card file, atomic replace."""
    with _Lock():
        for f in sorted((HOME / "cards").glob("recipe_*.json")):
            doc = json.loads(f.read_text(encoding="utf-8"))
            for c in doc["cards"]:
                if c.get("id") == recipe_id:
                    fn(c["plans"][app])
                    tmp = f.with_suffix(".json.tmp")
                    # allow_nan=False: a card file is strict JSON (a NaN that slipped past check raises here)
                    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False, allow_nan=False) + "\n",
                                   encoding="utf-8")
                    for k in range(50):  # Windows refuses the replace while another process reads the file
                        try:
                            tmp.replace(f)
                            break
                        except PermissionError:
                            if k == 49:
                                raise  # the .tmp stays: nothing is lost
                            time.sleep(0.05 * (k + 1))
                    pgd.cards.cache_clear()
                    return
    raise KeyError(recipe_id)


def record(recipe_id, app, key, value):
    """plans[app][key] = value in the recipe's card file. A new "run" moves the verdict on the run before it to
    verified_history (that verdict judged other frames), so the new run needs a judge again."""
    def fn(plan):
        if key == "run" and "verified" in plan:
            plan.setdefault("verified_history", []).append(plan.pop("verified"))
        plan[key] = value
    update_plan(recipe_id, app, fn)


def opaque(path):
    """a frame as RGB, transparency shown over a mid-grey checker (white and black paint both read on it)"""
    from PIL import Image
    with Image.open(path) as f:
        im = f.copy()  # the file is closed again at once (the full-size frame is deleted right after)
    if im.mode in ("RGBA", "LA", "PA") or im.mode == "P" and "transparency" in im.info:
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (140, 140, 140, 255))
        dark = Image.new("RGBA", (32, 32), (115, 115, 115, 255))
        for y in range(0, im.height, 32):
            for x in range((y // 32) % 2 * 32, im.width, 64):
                bg.paste(dark, (x, y))
        im = Image.alpha_composite(bg, im)
    return im.convert("RGB")


def strip(frames, out, captions):
    """the step frames as one contact sheet, STRIP_COLS per row, a caption under each"""
    from PIL import Image, ImageDraw, ImageFont
    w, h = STRIP_CELL
    cap = 22
    rows = (len(frames) + STRIP_COLS - 1) // STRIP_COLS
    sheet = Image.new("RGB", (STRIP_COLS * w, rows * (h + cap)), (24, 24, 24))
    draw, font = ImageDraw.Draw(sheet), ImageFont.load_default()
    for n, (fp, text) in enumerate(zip(frames, captions)):
        x, y = n % STRIP_COLS * w, n // STRIP_COLS * (h + cap)
        if fp and Path(fp).exists():
            im = opaque(fp)
            im.thumbnail((w, h))
            sheet.paste(im, (x + (w - im.width) // 2, y + (h - im.height) // 2))
        else:
            draw.text((x + 8, y + h // 2), "(no frame)", fill=(160, 160, 160), font=font)
        draw.text((x + 6, y + h + 4), text[:48], fill=(235, 235, 235), font=font)
    sheet.save(out)


_TAIL = r"[^\s'\",)\]]*"  # the rest of a path token
_ABS = re.compile(r"\b[A-Za-z]:[\\/]" + _TAIL)  # C:\x, C:\\x (a repr), C:/x
_UNC = re.compile(r"\\\\[^\\\s'\",)\]]+\\" + _TAIL)  # \\server\share\...
# /c/Users/x/..., /home/x/...; a name with spaces runs to the next slash (at most 64 characters)
_POSIX_HOME = re.compile(r"(?<![\w.])/(?:[A-Za-z]/)?(?:Users|home)/(?:[^/\r\n]{1,64}?/)?" + _TAIL)
# any profile folder, not only this machine's: C:\Users\<name with spaces>\... (the name runs to the next separator)
_PROFILE = re.compile(r"\b[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[^\\/\r\n]+?[\\/]" + _TAIL, re.I)
# spaced system folders: scrubbed through the first file extension, so a preset file named after a client goes too
# (ponytail: a folder path with no file name falls through to _ABS, which stops at the first space)
_SYSTEM = re.compile(r"\b[A-Za-z]:[\\/]{1,2}(?:Program Files(?: \(x86\))?|ProgramData)[\\/]{1,2}[^\r\n]{0,260}?"
                     r"\.\w{2,5}\b", re.I)


def _machine_roots():
    """(prefix, replacement), longest first: the repo folder -> '.', the user profile and temp folders (whose names may
    hold spaces) -> '<local path>' together with the rest of the path"""
    roots = {str(HOME): ".", str(CODE): "."}
    for p in (os.path.expanduser("~"), tempfile.gettempdir(), os.environ.get("TEMP"), os.environ.get("TMP")):
        if p and len(p) > 3:
            roots.setdefault(str(p), "<local path>")
    out = []
    for root, rep in roots.items():
        for form in {root, root.replace("\\", "/"), root.replace("\\", "\\\\")}:
            out.append((form, rep))
    return sorted(out, key=lambda x: -len(x[0]))


def public(text):
    """run notes are published in the recipe cards: the repo folder becomes '.', the user profile / temp folders and
    any other absolute, UNC or /c/Users path '<local path>'"""
    text = str(text)
    for form, rep in _machine_roots():
        tail = "" if rep == "." else _TAIL
        text = re.sub(re.escape(form) + tail, lambda m: rep, text, flags=re.I)
    text = _PROFILE.sub("<local path>", text)
    text = _SYSTEM.sub("<local path>", text)
    text = _UNC.sub("<local path>", text)
    text = _POSIX_HOME.sub("<local path>", text)
    return _ABS.sub("<local path>", text)


def result_of(steps):
    st = [s["status"] for s in steps]
    if "failed" in st:
        return "failed"
    if all(s == "manual" for s in st):
        return "manual"
    return "partial" if "manual" in st or any(s.get("unsent") for s in steps) else "complete"


def run_one(sess, recipe, app, do_record=True):
    key, plan = rkey(recipe), recipe["plans"][app]
    inp, csteps = plan_input(recipe, app), compile_plan(recipe, app)
    d = OUT / app
    sdir = d / "steps" / key
    sdir.mkdir(parents=True, exist_ok=True)
    for old in sdir.glob("*.png"):
        old.unlink()
    t0 = time.time()
    sess.out = HOME / "work" / "plans" / "out" / key / app  # a script's OUT folder: written files go here only
    sess.out.mkdir(parents=True, exist_ok=True)
    labels = open_input(sess, inp)
    frames, caps, steps = [sdir / "00_input.png"], [f"input: {inp['plate']}"], []
    sess.snap(frames[0])
    for cs in csteps:
        n = cs["step"]
        if cs.get("error"):
            rec = {"step": n, "status": "failed", "note": "plan error: " + cs["error"]}
        elif cs.get("manual"):
            rec = {"step": n, "status": "manual", "note": cs["manual"]}
        elif cs.get("target") and cs["target"] not in labels:
            rec = {"step": n, "status": "failed", "note": f"target {cs['target']!r} is not a label here "
                                                          f"(labels: {sorted(labels)})"}
        else:
            # the backend may re-point labels whose layer / shape the step replaced (Layer from Background ...)
            t1 = time.time()
            status, note, active = sess.step(cs, labels.get(cs.get("target")), labels)
            rec = {"step": n, "status": status, "note": public(note), "secs": round(time.time() - t1, 1)}
            if status == "ok" and cs.get("untyped") and app != "CDR":  # PS / AI ran it without some settings
                rec["unsent"] = True  # (CorelDRAW's gallery-form notes are by design, not a dropped value)
            if cs.get("as") and active is not None:
                labels[cs["as"]] = active
        steps.append(rec)
        fp = sdir / f"{n:02d}.png"
        if rec["status"] != "manual":
            sess.snap(fp)
        frames.append(fp if rec["status"] != "manual" else frames[-1])
        caps.append(f"{n} {rec['status']}: {cs['label']}")
        print(f"    step {n} {rec['status']}: {cs['label'][:60]}  {rec['note'][:120]}", flush=True)
    frame, full, crop = d / f"{key}.png", sdir / "final_full.png", d / f"{key}_1to1.png"
    layers = sess.export(full)
    from PIL import Image
    im = opaque(full)
    im.resize(FRAME, Image.LANCZOS).save(frame)
    crop.unlink(missing_ok=True)
    if hasattr(sess, "detail"):
        sess.detail(crop)  # the app exports the region itself (CorelDRAW: the page at 100 %)
    elif getattr(sess, "exports_doc_pixels", False):  # the export is the document's own pixels: crop the region
        # scaled to the document (an upscaled one shows the same region bigger, a downsized one smaller)
        x, y, w, h = (round(v * im.width / 1920) for v in DETAIL)
        im.crop((x, y, x + w, y + h)).save(crop)
    full.unlink()
    strip(frames, d / f"{key}_steps.png", caps)
    sess.close()
    run = {"date": time.strftime("%Y-%m-%d"), "app_version": sess.version, "input": inp, "plan_hash": plan_hash(plan),
           "result": result_of(steps), "steps": steps, "layers": [public(x) for x in layers],
           "frame": frame.relative_to(HOME).as_posix(), "strip": (d / f"{key}_steps.png").relative_to(HOME).as_posix(),
           "secs": round(time.time() - t0, 1)}
    if crop.exists():
        run["crop"] = {"file": crop.relative_to(HOME).as_posix(), "box": list(DETAIL), "of": "1920x1080 frame",
                       "scale": "1:1 document pixels"}
    if do_record:
        record(recipe["id"], app, "run", run)
    return run


def cmd_list(app=None):
    for r in recipes():
        for a, plan in r["plans"].items():
            if app and a != app:
                continue
            try:
                cs = compile_plan(r, a)
                man = sum(1 for s in cs if s.get("manual") or s.get("error"))
                bad = sum(1 for s in cs if s.get("error"))
                cov = f"{len(cs) - man}/{len(cs)} routed" + (f" {bad} ERR" if bad else "")
            except Exception as e:  # noqa: BLE001
                cov = f"COMPILE ERROR {e}"
            run, ver = plan.get("run") or {}, plan.get("verified") or {}
            stale = run and run.get("plan_hash") != plan_hash(plan)
            vstale = ver and ver.get("plan_hash") != plan_hash(plan)
            print(f"{a:3} {rkey(r):55} {cov:13} run={run.get('result', '-')}{' (stale)' if stale else ''}"
                  f" verdict={ver.get('verdict', '-')}{' (stale)' if vstale else ''}")


def cmd_show(what, app=None):
    for r in select(what):
        for a in r["plans"]:
            if app and a != app:
                continue
            print(f"== {r['name']} [{a}] input={json.dumps(plan_input(r, a))}")
            for s in compile_plan(r, a):
                body = (s.get("error") and f"PLAN ERROR: {s['error']}" or s.get("manual") and f"MANUAL: {s['manual']}"
                        or json.dumps(s["op"], ensure_ascii=False)[:400])
                tgt = f" target={s['target']}" if s.get("target") else ""
                print(f"  {s['step']:2} {s['kind']:15} {s['label'][:50]}{tgt}{' as=' + s['as'] if s.get('as') else ''}\n"
                      f"       {body}")


def cmd_run(what, apps, force=False, do_record=True):
    """-> 0 when every plan ran (complete, partial or manual), 1 when one failed or crashed, 2 when nothing matched"""
    todo = [(r, a) for r in select(what) for a in r["plans"] if not apps or a in apps]
    if not todo:
        _usage(f"no {'/'.join(apps) or 'app'} plan in {what!r} (python run_plan.py list)")
    by_app, summary = {}, {}
    photo = (HOME / "media" / "plate_photo.png").exists()
    for r, a in todo:
        plan = r["plans"][a]
        done = (plan.get("run") or {}).get("plan_hash") == plan_hash(plan) and (HOME / plan["run"]["frame"]).exists()
        if done and not force:
            print(f"skip {a} {rkey(r)}: its recorded run matches the plan (--force to run again)")
            continue
        if plan_input(r, a).get("plate") == "photo" and not photo:  # checked before an app is started
            print(f"skip {a} {rkey(r)}: media/plate_photo.png is missing (put a 1920x1080 photo at "
                  "media/test_photo.png and run media/make_plates.py)", flush=True)
            summary[f"{a} {rkey(r)}"] = "error: media/plate_photo.png missing"
            continue
        by_app.setdefault(a, []).append(r)
    for a, rs in by_app.items():
        sess = backend(a).Session()
        try:
            for r in rs:
                print(f"{a} {rkey(r)}: {r['name']}", flush=True)
                try:
                    run = run_one(sess, r, a, do_record)
                except Exception as e:  # noqa: BLE001 (one plan's crash is reported; the next one runs)
                    print(f"  RUN ERROR {type(e).__name__}: {e}", flush=True)
                    sess.recover(e)
                    summary[f"{a} {rkey(r)}"] = f"error: {e}"[:200]
                    continue
                summary[f"{a} {rkey(r)}"] = run["result"]
                print(f"  -> {run['result']} ({run['secs']} s)", flush=True)
        finally:
            sess.quit()
    print(json.dumps(summary, indent=1))
    return 1 if any(v == "failed" or str(v).startswith("error:") for v in summary.values()) else 0


def cmd_strip(what, app):
    for r in select(what):
        if app not in r["plans"]:
            continue
        key, sdir = rkey(r), OUT / app / "steps" / rkey(r)
        run = r["plans"][app].get("run") or {}
        frames, caps = [sdir / "00_input.png"], ["input"]
        for s in run.get("steps", []):
            fp = sdir / f"{s['step']:02d}.png"
            frames.append(fp if fp.exists() else frames[-1])
            caps.append(f"{s['step']} {s['status']}")
        strip(frames, OUT / app / f"{key}_steps.png", caps)


def cmd_get(what, app, out=None):
    """the plan as JSON (run / verified left out): edit it, then put it back. With out, written there as UTF-8 (no
    BOM): a shell redirect may re-encode the text (Windows PowerShell writes UTF-16 or the console code page)."""
    r = select_one(what, app)
    text = json.dumps({k: v for k, v in r["plans"][app].items() if k not in UNTRACKED}, indent=1, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {app} plan of {r['id']} to {out}")
    else:
        print(text)


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def cmd_put(what, app, path):
    """replace the plan after pgd.check_plan and a compile pass both accept it; its run / verified records stay (they
    go stale by plan_hash when the plan changed)"""
    r = select_one(what, app)
    try:
        new = json.loads(Path(path).read_bytes())  # UTF-8 (a BOM is fine) or UTF-16 / 32
    except (OSError, ValueError) as e:
        print(f"NOT SAVED: cannot read {path} as JSON: {e}")
        return 1
    if not isinstance(new, dict):
        print(f"NOT SAVED: a plan is a JSON object, got {type(new).__name__}")
        return 1
    new = {k: v for k, v in new.items() if k not in UNTRACKED}
    new.setdefault("app", app)
    garbled = sorted({s for s in _strings(new) if "\ufffd" in s or "\u0393\u00c7" in s or "\u00e2\u20ac" in s})
    if new.get("app") != app:
        issues = [f"plan app is {new.get('app')!r}, this is the {app} slot"]
    elif garbled:
        issues = [f"text that was re-encoded on its way here (mojibake or U+FFFD): {garbled[0][:80]!r}; write the plan "
                  f"with `python run_plan.py get {what} {app} plan.json` and edit that file"]
    else:
        # checked as it will run: with the input the runner uses (the family default when the plan names none)
        issues = pgd.check_plan(dict(new, input=plan_input(dict(r, plans={**r["plans"], app: new}), app)))
        issues += [f"step {i}: a {app} plan runs only {app} steps (this one is {st.get('kind')})"
                   for i, st in enumerate(new.get("steps") or [], 1) if isinstance(st, dict) and
                   (st.get("app", app) != app or not str(st.get("kind") or "").startswith(app.lower() + "_"))]
    try:
        bad = [f"step {s['step']}: {s['error']}" for s in compile_plan(dict(r, plans={**r["plans"], app: new}), app)
               if s.get("error")]
    except Exception as e:  # noqa: BLE001
        bad = [f"compile: {e}"]
    if issues or bad:
        print("NOT SAVED:\n" + "\n".join(dict.fromkeys(issues + bad)))
        return 1

    def swap(plan):
        keep = {k: plan[k] for k in UNTRACKED if k in plan}
        plan.clear()
        plan.update(new, **keep)
    update_plan(r["id"], app, swap)
    print(f"saved {app} plan of {r['id']} (hash {plan_hash(new)})")
    return 0


def cmd_judge(what, app, verdict, note, by, second=None):
    """the judge's verdict on the current recorded run, against the recipe's summary. With --second: an independent
    second opinion on that verdict ("agree" or "corrected: ..."); a --verdict given with it replaces the verdict and
    keeps the first one as verified.previous; a new first opinion on the same run keeps the one it replaces there."""
    r = select_one(what, app)
    plan = r["plans"][app]
    run = plan.get("run") or {}
    if run.get("plan_hash") != plan_hash(plan):
        raise SystemExit("no current run to judge: the plan changed since its recorded run (run it again first)")
    if second is not None:
        old = plan.get("verified") or {}
        if old.get("plan_hash") != run["plan_hash"]:
            raise SystemExit("no verdict on the current run to give a second opinion on")
        new = dict(old, second_opinion=second)
        if verdict and verdict != old.get("verdict"):
            if verdict not in VERDICTS:
                raise SystemExit(f"--verdict must be one of {VERDICTS}")
            new = dict(new, verdict=verdict, note=note or old.get("note"), by=by or old.get("by"),
                       previous={k: old[k] for k in ("verdict", "note", "by", "date") if k in old})
        record(r["id"], app, "verified", new)
        print(f"{app} {rkey(r)}: {new['verdict']} (second opinion: {second})")
        return 0
    if verdict not in VERDICTS:
        raise SystemExit(f"--verdict must be one of {VERDICTS}")
    if not (note or "").strip() or not (by or "").strip():
        raise SystemExit("a verdict needs --note (what the frame shows) and --by (who judged)")
    new = {"verdict": verdict, "note": note, "date": time.strftime("%Y-%m-%d"), "by": by, "plan_hash": run["plan_hash"]}
    old = plan.get("verified") or {}
    if old.get("plan_hash") == run["plan_hash"]:
        new["previous"] = {k: old[k] for k in ("verdict", "note", "by", "date") if k in old}
    record(r["id"], app, "verified", new)
    print(f"{app} {rkey(r)}: {verdict}")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("list", "show", "run", "strip", "get", "put", "judge"))
    ap.add_argument("what", nargs="?")
    ap.add_argument("apps", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--verdict")
    ap.add_argument("--note", default="")
    ap.add_argument("--by", default="")
    ap.add_argument("--second")
    a = ap.parse_args(argv)

    def app_arg(x):
        if x.upper() not in APPS:
            _usage(f"unknown app {x!r}: one of {', '.join(APPS)}")
        return x.upper()
    if a.cmd == "list":
        cmd_list(app_arg(a.what) if a.what else None)
        return 0
    if not a.what:
        _usage(f"{a.cmd} needs a recipe{', family, all or a comma list' if a.cmd in ('run', 'show', 'strip') else ''} "
               "(python run_plan.py list)")
    # the slots that are apps: every positional of run, the first of the others (put's second is the plan file)
    n_apps = {"run": len(a.apps), "show": min(len(a.apps), 1)}.get(a.cmd, 1)
    need = {"get": (1, 2), "put": (2, 2), "judge": (1, 1), "strip": (1, 1), "show": (0, 1), "run": (0, 99)}[a.cmd]
    if not need[0] <= len(a.apps) <= need[1]:
        _usage(f"{a.cmd} takes <recipe>{' APP' if need[0] else ' [APP]'}"
               f"{' plan.json' if a.cmd == 'put' else ' [plan.json]' if a.cmd == 'get' else ''}")
    apps = [app_arg(x) for x in a.apps[:n_apps]]
    if a.cmd == "get":
        return cmd_get(a.what, apps[0], a.apps[1] if len(a.apps) > 1 else None) or 0
    if a.cmd == "put":
        return cmd_put(a.what, apps[0], a.apps[1])
    if a.cmd == "judge":
        return cmd_judge(a.what, apps[0], a.verdict, a.note, a.by, a.second)
    if a.cmd == "show":
        cmd_show(a.what, apps[0] if apps else None)
    elif a.cmd == "run":
        return cmd_run(a.what, apps, a.force, not a.no_record)
    elif a.cmd == "strip":
        cmd_strip(a.what, apps[0])
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
