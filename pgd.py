"""PGD ("professional graphics designer"): what Photoshop 2026, Illustrator 2026 and CorelDRAW 2024 can do, harvested
from the installed apps, written up as knowledge cards and render-tested. Design systems read it to choose effects,
tools and presets, and to check a plan before anything is sent to an app.

    python pgd.py find "neon glow" [PS|AI|CDR] [kind]   search cards (name, look, path, summary, use_for)
    python pgd.py card "Gaussian Blur" [PS|AI|CDR]      one card in full (by name, id or menu path)
    python pgd.py equiv "Gaussian Blur" [PS|AI|CDR]     the same effect in the other two apps
    python pgd.py items AI "drop shadow"                search the raw harvest (names, ids, paths)
    python pgd.py check plan.json                       pre-flight a design plan (see check_plan)
    python pgd.py stats                                 what PGD knows

App codes may be written in any case (a full app name such as photoshop, or a misspelt kind such as ps_filtr, at the end
of a find query is a usage error). Exit codes: 0 ok, 1 check found issues, 2 usage error or an unreadable plan /
data folder.

    import sys; sys.path.insert(0, "<path to PGD>"); import pgd
    pgd.find("halftone", app="PS"); pgd.check_plan(plan) -> [issues]

Data (cards/, harvest/) is read from $PGD_HOME when set, else from this file's folder.
"""
import json, math, os, re, sys, time
from collections import Counter
from functools import lru_cache
from pathlib import Path

CODE = Path(__file__).resolve().parent
HERE = Path(os.environ.get("PGD_HOME") or CODE)
APPS = ("PS", "AI", "CDR")
USABLE = ("current", "needs_input")
# input "damage" on the photo plate (run_plan.damaged_photo, run_plan.DAMAGE says what each does): key -> (min, max)
INPUT_DAMAGE = {"noise": (0, 255), "dust": (0, 10000), "scratches": (0, 1000), "jpeg": (1, 100), "blur": (0, 200),
                "haze": (0, 1), "tilt": (-45, 45)}
# run_plan.py input plates -> the labels each names (a plan's "target" picks one; "as" adds more); input_labels() gives
# the set one app's backend really makes
INPUT_LABELS = {"photo": ["photo"], "text": ["type", "background"], "blank": ["background"],
                "vector": ["art", "orange_box", "blue_star", "grad_circle", "pgd_type", "zigzag"]}
# what each backend leaves active after opening the input (plan_ps OPEN: the type layer whenever there is text;
# plan_ai MAIN and plan_cdr MAIN use these tables)
OPEN_ACTIVE = {"PS": {"photo": "photo", "text": "type", "blank": "background"},
               "AI": {"vector": "art", "photo": "photo", "text": "type", "blank": "background"},
               "CDR": {"vector": "blue_star", "photo": "photo", "text": "type", "blank": "background"}}
# the closed plan schema check_plan holds a plan to (run_plan.py writes run / verified / verified_history)
PLAN_KEYS = ("app", "input", "steps", "note", "run", "verified", "verified_history")
STEP_KEYS = ("app", "kind", "id", "name", "settings", "effects", "target", "as", "script", "labels", "note")
EFFECT_KEYS = ("id", "name", "settings", "note")
INPUT_KEYS = ("plate", "text", "font", "size", "color", "background", "at", "damage")


def _code_path():
    """CODE on sys.path once (validate_cards / prepare_batches live next to this file)"""
    if str(CODE) not in sys.path:
        sys.path.insert(0, str(CODE))


def _read_json(f):
    """a JSON file (a UTF-8 BOM is fine), read once more after a moment when it fails (a writer may be mid-write)"""
    for i in range(2):
        try:
            return json.loads(Path(f).read_bytes())
        except (OSError, ValueError):
            if i:
                raise
            time.sleep(0.2)


@lru_cache(None)
def _load_cards():
    out, bad = [], []
    for f in sorted((HERE / "cards").glob("*.json")):
        try:
            out += _read_json(f).get("cards", [])
        except Exception:  # noqa: BLE001 (reported by unreadable(): check_plan fails on it, queries warn)
            bad.append(f"cards/{f.name}")
    return out, bad


def cards():
    return _load_cards()[0]


cards.cache_clear = _load_cards.cache_clear  # run_plan.py re-reads the cards after it writes one


@lru_cache(None)
def _load_harvest():
    out, bad = {}, []
    for f in sorted((HERE / "harvest").glob("*/*.json")):
        try:
            d = _read_json(f)
            out[(d["app"], d["kind"])] = {it["id"]: it for it in d["items"]}
        except Exception:  # noqa: BLE001
            bad.append(f"harvest/{f.parent.name}/{f.name}")
    return out, bad


def harvest():
    """(app, kind) -> {id: item}"""
    return _load_harvest()[0]


harvest.cache_clear = _load_harvest.cache_clear


def unreadable():
    """card and harvest files that could not be read: their items are missing from every answer"""
    return _load_cards()[1] + _load_harvest()[1]


def _strs(x):
    return [x] if isinstance(x, str) else [str(v) for v in x or []]


def _words(q):
    return [w for w in re.split(r"\W+", q.lower()) if w]


_PARTICLES = {"ko", "ka", "ki", "ke", "pe", "se", "mein", "banao", "lagao", "karo"}  # Hinglish glue words: never matched
_ALSO = {"hatao": "remove"}  # searched as well as the word itself
_SUFFIX = ("isation", "ization", "ising", "izing", "ised", "ized", "ise", "ize", "ing", "ed", "es", "s", "e")


def _stem(w):
    """a light stem, so extruded / extrude / extrudes and glowing / glow meet"""
    if w.endswith("ss"):
        return w
    for suf in _SUFFIX:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


def _toks(*parts):
    return {_stem(w) for p in parts for w in _words(p) if len(w) > 1}


_IDX = {}


def _index():
    """per card its stemmed word sets (name, look, path, summary + use_for) and each word's document frequency; built
    once per card list (rebuilt after cards.cache_clear())"""
    cs = cards()
    if _IDX.get("of") is not cs:
        idx, df = [], Counter()
        for c in cs:
            f = (_toks(c.get("name") or ""), _toks(*_strs(c.get("look"))), _toks(c.get("path") or ""),
                 _toks(c.get("summary") or "", *_strs(c.get("use_for"))))
            idx.append((c, f))
            df.update(set().union(*f))
        _IDX.update(of=cs, idx=idx, df=df)
    return _IDX["idx"], _IDX["df"]


def _in_app(c, app):
    """a card of `app`, or a recipe with a plan for it"""
    return c.get("app") == app or app in (c.get("plans") or {})


def find(query, app=None, kind=None, limit=25):
    """Rank cards by the query's whole words (lightly stemmed, one-letter words and Hinglish particles left out, each
    word counted once, rare words weighing more) found in the name (x3), look (x2), or path / summary / use_for (x1).
    Covering more of the query ranks higher; a card whose name is exactly the query higher still. Unless `kind` asks for
    them, preset cards count 0.7 and API cards 0.4 (ask for a scripting class with kind="ps_api" ...); obsolete, hidden
    and unusable cards count 0.6; a render pass adds a little. A recipe counts as a card of every app it has a plan
    for."""
    idx, df = _index()
    ws = [w for w in _words(query) if len(w) > 1 and w not in _PARTICLES]
    words = list(dict.fromkeys(_stem(w) for w in ws + [_ALSO[w] for w in ws if w in _ALSO]))
    if not words:
        return []
    n, scored = len(idx), []
    for c, (nm, lk, pa, tx) in idx:
        if app and not _in_app(c, app) or kind and c.get("kind") != kind:
            continue
        hit = [3 * (w in nm) or 2 * (w in lk) or int(w in pa or w in tx) for w in words]
        s = sum(math.log(1 + n / df.get(w, 1)) * h for w, h in zip(words, hit))
        if not s:
            continue
        s *= 1 + sum(1 for h in hit if h) / len(words)
        if set(words) == nm:
            s *= 1.5
        k = c.get("kind") or ""
        if not kind:
            s *= 0.4 if k.endswith("_api") else 0.7 if k.endswith("_preset") else 1
        if c.get("status") not in USABLE:
            s *= 0.6
        s += 0.5 * ((c.get("verified") or {}).get("verdict") == "pass")
        scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:limit]]


_TIER_RANK = {"visual": 0, "tool": 1, "menu": 2, "recipe": 2, "preset": 3, "api": 4}


@lru_cache(None)
def _tier(kind):
    _code_path()
    from prepare_batches import tier
    return tier(kind) if "_" in (kind or "") else (kind or "")


def card(name, app=None, like=None):
    """By name, id or menu path (equivalents may hold any of the three). Of several hits: usable ones first, then, when
    `like` names the kind of the card a lookup starts from (equiv), those of the same tier (visual / tool / menu /
    preset / api), then visual > tool > menu > preset > api. With `app`, only that app's cards (a recipe counts for
    every app it has a plan for), else None."""
    n = (name or "").strip().lower() if isinstance(name, str) else ""
    if not n:
        return None
    hit = [c for c in cards() if n in ((c.get("name") or "").lower(), (c.get("id") or "").lower(),
                                       (c.get("path") or "").lower())]
    if app:
        hit = [c for c in hit if _in_app(c, app)]
    t0 = _tier(like) if like else None
    hit.sort(key=lambda c: (c.get("status") not in USABLE, t0 is not None and _tier(c.get("kind")) != t0,
                            _TIER_RANK.get(_tier(c.get("kind")), 5)))
    return hit[0] if hit else None


def equiv(name, app=None):
    """The card for `name` (in `app` when given) plus the cards its equivalents point at, and usable cards in other apps
    that point back at it."""
    c = card(name, app)
    if not c:
        return {}
    out = {c["app"]: f"{c['name']} [{c['kind']} {c['id']}]"}
    for a, other in (c.get("equivalents") or {}).items():
        o = other and card(str(other), a, like=c.get("kind"))
        if o:
            out[a] = f"{o['name']} [{o['kind']} {o['id']}]"
        elif other:
            out[a] = f"{other} (no card)"
    mine, back = {c["name"].lower(), c["id"].lower(), (c.get("path") or "").lower()} - {""}, {}
    for o in cards():
        b = str((o.get("equivalents") or {}).get(c["app"]) or "").lower()
        if o.get("app") not in out and b and b in mine and o.get("status") in USABLE:
            back.setdefault(o["app"], []).append(o)
    t0 = _tier(c.get("kind"))
    for a, os_ in back.items():  # of several cards pointing back: the same tier first, then visual > ... > api
        o = min(os_, key=lambda o: (_tier(o.get("kind")) != t0, _TIER_RANK.get(_tier(o.get("kind")), 5)))
        out[a] = f"{o['name']} [{o['kind']} {o['id']}]"
    return out


def items(app, query, limit=40):
    words, res, app = _words(query), [], (app or "").upper()
    for (a, kind), its in harvest().items():
        if a != app:
            continue
        for it in its.values():
            hay = " ".join(str(it.get(k, "")) for k in ("name", "id", "path", "category")).lower()
            if all(w in hay for w in words):
                res.append(f"[{kind}] {it['name']}  id={it['id']}  path={it.get('path', '')}")
    return res[:limit]


def _lookup(app, kind, step):
    """the harvested item a step names: by id, else by name or menu path (several by that name -> the list)"""
    its = harvest().get((app, kind)) or {}
    i = step.get("id")
    if isinstance(i, str) and i in its:
        return its[i]
    n = step.get("name")
    n = n.lower() if isinstance(n, str) else ""
    if not n:  # an unknown id and no name: nothing, not every item with an empty path
        return None
    hit = [it for it in its.values() if it["name"].lower() == n or (it.get("path") or "").lower() == n]
    return hit[0] if len(hit) == 1 else (hit or None)


def _whole_style(kind, it):
    """Steps that replace the target's style instead of adding to it: a ps_layer_style step writes the layer's whole
    layerEffects set (a Styles preset too), an Illustrator graphic style (applyTo) replaces the appearance."""
    return kind == "ps_layer_style" or kind.endswith("_preset") and it.get("category") in ("Layer style", "Graphic Style")


# After these the next step acts on another layer / object.
_RETARGET = ("Layer/New/", "Layer/New Fill Layer/", "Layer/New Adjustment Layer/", "Layer/Duplicate Layer",
             "Layer/Group Layers", "Layer/Merge", "Layer/Flatten Image", "Layer/Smart Objects/New Smart Object via Copy",
             "File/Place", "Edit/Paste", "Object/Group", "Object/Expand")
# After these the same label names a layer with no live style of its own (the smart object embeds the styled layer;
# Rasterize Layer Style bakes the effects into pixels), so a later style step replaces nothing.
_UNSTYLE = ("Layer/Smart Objects/Convert to Smart Object", "Layer/Rasterize/Layer Style")
_FIX = {"PS": "merge the layer effects into one ps_layer_style step with \"effects\", or move this one to another layer "
              "(Duplicate Layer, a new layer, a \"target\")",
        "AI": "apply the graphic style first and the live effects after it, or put it on another object (Paste in Front, "
              "Group, a \"target\")"}


def missing_required(it, settings):
    """CorelDRAW object-model calls (cdr_com Shape.Create*) take positional arguments: the params the harvest marks
    required (extra.required: no default and not optional in the signature; colours / objects excepted, they may be
    None) that `settings` leaves out, which the call cannot get."""
    inv = (it.get("invoke") or {}).get("cdr_com") or ""
    if not inv or (it.get("extra") or {}).get("effect_id"):
        return []
    have = set(settings or {})
    return [p["key"] for p in it.get("params") or [] if (p.get("extra") or {}).get("required")
            and p.get("type") not in ("color", "object") and p["key"] not in have and p["name"] not in have
            and not (p["key"] == "Type" and (it.get("extra") or {}).get("lens_type") is not None)
            and not (p["key"] in ("OriginX", "OriginY") and "Distortion" in inv)]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _setting(sub, it, key):
    """a layer-effect value from the step's settings (by key or param name), else the harvested default; an enum label
    ("outside") stands for its value ("outsetFrame"), as the compile maps it"""
    p = next((p for p in it.get("params") or [] if p.get("key") == key), {})
    s = sub.get("settings") or {}
    v = s.get(key, s.get(p.get("name"), p.get("default")))
    return next((e.get("value") for e in p.get("enum") or [] if isinstance(v, str) and v == e.get("label")), v)


def _shadow_under_stroke(where, pairs):
    """a Drop Shadow that moves no further than an outside / centred Stroke on the same layer reaches is drawn under
    the stroke and never shows (plan runs 2026-10-15: four Photoshop plans lost their shadow this way). The shadow's
    Size (blur) beyond the 5 px those runs used counts at half: a soft halo spreads past the stroke.
    ponytail: the blur weight is a heuristic; calibrate it with one live render pair. Values that are not finite
    numbers are skipped here (the value check reports them)."""
    reach = []
    for s, it in pairs:
        style = _setting(s, it, "style")
        size = _num(_setting(s, it, "size") or 0)
        if it["id"] == "frameFX" and style in ("outsetFrame", "centeredFrame") and size is not None:
            reach.append(size / (1 if style == "outsetFrame" else 2))
    out = []
    for s, it in pairs:
        if it["id"] == "dropShadow" and reach:
            d, b = _num(_setting(s, it, "distance") or 0), _num(_setting(s, it, "blur") or 0)
            if d is None or b is None:
                continue
            if d + max(b - 5, 0) / 2 <= max(reach):
                out.append(f"{where}: Drop Shadow distance {d:g} px (Size {b:g} px) does not reach past the "
                           f"{max(reach):g} px the outside Stroke covers, so the shadow is hidden under the stroke: make "
                           "the distance larger than the stroke size (or move the stroke inside)")
    return out


def input_labels(app, inp):
    """the labels `app`'s backend gives the input document (plan_ps / plan_ai / plan_cdr open): the plate's
    INPUT_LABELS and "type" when the input has text. Photoshop has no vector plate and no "background" on the photo
    plate; "art" (the whole vector plate) is Illustrator's only; Illustrator and CorelDRAW add "background" whenever
    the input sets one."""
    plate = inp.get("plate")
    out = set(INPUT_LABELS.get(plate, ())) if isinstance(plate, str) else set()
    if app == "PS" and plate == "vector":
        out = set()
    if app == "CDR":
        out.discard("art")
    if app in ("AI", "CDR") and inp.get("background"):
        out.add("background")
    if inp.get("text"):
        out.add("type")
    return out


def _plan_shape(plan):
    """structure problems (the closed schema: PLAN_KEYS, STEP_KEYS, EFFECT_KEYS and the type of each value); when there
    are any, check_plan reports only these"""
    if not isinstance(plan, dict):
        return [f"plan: expects an object {{\"app\": ..., \"steps\": [...]}}, got {type(plan).__name__}"]
    out = [f"plan: unknown key {k!r} (a plan has {', '.join(PLAN_KEYS)})" for k in plan if k not in PLAN_KEYS]
    if "app" in plan and not isinstance(plan["app"], str):
        out.append(f"plan: app must be a string (PS / AI / CDR), got {plan['app']!r}")
    if "input" in plan and not isinstance(plan["input"], dict):
        out.append(f"input: expects an object {{\"plate\": ...}}, got {plan['input']!r}")
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return out + [f"plan: \"steps\" must be a list of steps, got {steps!r}"]
    for i, st in enumerate(steps, 1):
        w = f"step {i}"
        if not isinstance(st, dict):
            out.append(f"{w}: expects an object {{\"kind\": ..., \"id\" | \"name\": ...}}, got {st!r}")
            continue
        out += [f"{w}: unknown key {k!r} (a step has {', '.join(STEP_KEYS)})" for k in st if k not in STEP_KEYS]
        out += [f"{w}: {k} must be a string, got {st[k]!r}" for k in ("app", "kind", "id", "name", "target", "as")
                if k in st and not isinstance(st[k], str)]
        if "settings" in st and not isinstance(st["settings"], dict):
            out.append(f"{w}: settings must be an object {{param: value}}, got {st['settings']!r}")
        if "labels" in st and not (isinstance(st["labels"], list) and all(isinstance(x, str) for x in st["labels"])):
            out.append(f"{w}: labels must be a list of strings, got {st['labels']!r}")
        if "effects" in st:
            fx = st["effects"]
            if not (isinstance(fx, list) and fx and all(isinstance(e, dict) for e in fx)):
                out.append(f"{w}: effects must be a non-empty list of objects {{\"name\" | \"id\", \"settings\"}}")
            else:
                for j, e in enumerate(fx, 1):
                    out += [f"{w} effect {j}: unknown key {k!r} (an effect has {', '.join(EFFECT_KEYS)})"
                            for k in e if k not in EFFECT_KEYS]
                    out += [f"{w} effect {j}: {k} must be a string, got {e[k]!r}" for k in ("id", "name")
                            if k in e and not isinstance(e[k], str)]
                    if "settings" in e and not isinstance(e["settings"], dict):
                        out.append(f"{w} effect {j}: settings must be an object, got {e['settings']!r}")
            out += [f"{w}: {k!r} beside \"effects\" is never sent (each effect carries its own name and settings)"
                    for k in ("id", "name", "settings") if k in st]
    return out


def _input_issues(inp, app):
    _code_path()
    from validate_cards import finite
    out, plate = [], inp.get("plate")
    if not (isinstance(plate, str) and plate in INPUT_LABELS):  # missing too: the runner opens inp["plate"]
        out.append(f"input: plate {plate!r} is not one of {sorted(INPUT_LABELS)}")
    for k, v in inp.items():
        if k not in INPUT_KEYS:
            out.append(f"input: unknown key {k!r} (an input has {', '.join(INPUT_KEYS)})")
        elif k in ("text", "font") and not isinstance(v, str):
            out.append(f"input: {k} must be a string, got {v!r}")
        elif k == "size" and not (finite(v) and v > 0):
            out.append(f"input: size must be a number of px > 0, got {v!r}")
        elif k in ("color", "background") and not (isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v)):
            out.append(f"input: {k} expects \"#RRGGBB\", got {v!r}")
        elif k == "at" and not (isinstance(v, list) and len(v) == 2 and all(finite(x) for x in v)):
            out.append(f"input: at expects [x, y] in px, got {v!r}")
        elif k == "damage":
            if plate != "photo" or not isinstance(v, dict):
                out.append('input: "damage" is a dict on the photo plate ({"noise": 12, "dust": 80, ...})')
                continue
            for dk, dv in v.items():
                if dk not in INPUT_DAMAGE:
                    out.append(f"input: damage {dk!r} is not one of {sorted(INPUT_DAMAGE)}")
                elif not (finite(dv) and INPUT_DAMAGE[dk][0] <= dv <= INPUT_DAMAGE[dk][1]):
                    out.append(f"input: damage {dk} must be a number from {INPUT_DAMAGE[dk][0]} to "
                               f"{INPUT_DAMAGE[dk][1]}, got {dv!r}")
    if not out and plate == "vector" and app == "PS":
        out.append("input: the vector plate is for Illustrator / CorelDRAW; a Photoshop plan starts from photo, text or "
                   "blank")
    return out


def check_plan(plan):
    """Pre-flight a design plan: {"app": "PS", "steps": [{"kind": "ps_filter", "name" | "id": ..., "settings": {...}}]}
    (a step may carry its own "app"). Never raises: every problem comes back as one issue line. Flags
    - a plan that is not that shape: keys outside PLAN_KEYS / STEP_KEYS / EFFECT_KEYS / INPUT_KEYS, "steps" missing or
      not a list, a step, settings, effects or labels of the wrong type, name / settings beside "effects";
    - unknown items, ambiguous names, a name that contradicts the id, unknown params, wrong types (a string param takes
      a string; NaN / Infinity are no numbers; object / list members are checked against their declared types),
      out-of-range values and enums, CorelDRAW object-model calls missing a param the harvest marks required;
    - items whose card says they are hidden / unusable or whose render test failed, and card or harvest files that
      could not be read (their items are then not checked).

    A step acts on the active layer / selection, or on the one its optional "target" names ("target": "type layer");
    items that make or switch layers / objects (Duplicate Layer, fill and adjustment layers, Layer Via Copy, Merge,
    Paste, Group, Expand Appearance ...) move the active one. A whole-style step replaces the style instead of adding to
    it (a ps_layer_style step writes the layer's whole layerEffects set, so does a Styles preset; an Illustrator graphic
    style replaces the appearance, live effects included), so a second one on the same target is flagged: a step-by-step
    run would keep only the last. Several effects on one layer go in ONE step, sent as one layerEffects descriptor:
    {"kind": "ps_layer_style", "effects": [{"name": "Stroke", "settings": {...}}, {"name": "Drop Shadow", ...}]}
    (an effect repeated there goes in its multi list, e.g. dropShadowMulti; one without a multi key is flagged).

    Runnable plans (run_plan.py) also carry "input" (the document they start from: {"plate": "photo" | "text" |
    "vector" | "blank", ...}, checked key by key); then every "target" must be a label: one the app's backend gives the
    input (input_labels), one an earlier step gave what it left active with "as", or one a CorelDRAW script step lists
    in "labels" (the labels its script adds); the first untargeted step acts on what the backend left active
    (OPEN_ACTIVE), and every step must be of the plan's app (another app's step would be skipped as manual). A "script"
    is the step's own source code (ExtendScript for PS / AI, Python for CDR), run instead of the item's route, so the
    item's required values are not asked of it."""
    _code_path()
    from validate_cards import check_value, param_index  # one implementation of the value rules
    issues = [f"{f}: unreadable, so the items it holds were not checked" for f in unreadable()]
    shape = _plan_shape(plan)
    if shape:
        return issues + shape
    app0 = plan.get("app")
    target, styled = None, {}  # styled: target -> last step that set its whole style / appearance
    inp, alias, labels = plan.get("input") or {}, {}, None  # alias: an "as" label -> the target it names
    plate = inp.get("plate") if isinstance(inp.get("plate"), str) else None  # a list / dict plate is unhashable
    if inp:
        issues += _input_issues(inp, app0)
        if app0 not in APPS:
            issues.append('plan: a runnable plan (with "input") needs "app" (PS / AI / CDR)')
        labels = input_labels(app0, inp)
        target = "type" if app0 == "PS" and inp.get("text") else OPEN_ACTIVE.get(app0, {}).get(plate)

    def item(app, kind, st, where):
        it = _lookup(app, kind, st)
        if it is None:
            issues.append(f"{where}: no {app} {kind} by that name or id (search: python pgd.py items {app} \"...\")")
            return None
        if isinstance(it, list):
            issues.append(f"{where}: name is ambiguous in {app} {kind}: use an id from {[x['id'] for x in it][:6]}")
            return None
        if st.get("id") == it["id"] and st.get("name") and st["name"].lower() not in (
                it["name"].lower(), (it.get("path") or "").lower()):
            issues.append(f"{where}: id {it['id']!r} is {it['name']!r}, not {st['name']!r}")
        idx = param_index(it)
        for k, v in (st.get("settings") or {}).items():
            if k not in idx:
                issues.append(f"{where}: {it['name']} has no param {k!r} (has {list(idx)[:30]})")
            else:
                e = check_value(k, idx[k], v)
                if e:
                    issues.append(f"{where}: {e}")
        miss = missing_required(it, st.get("settings")) if kind == "cdr_effect" and "script" not in st else []
        if miss:
            issues.append(f"{where}: {it['name']} needs {', '.join(miss)} (required; the call takes them positionally)")
        c = next((c for c in cards() if c.get("id") == it["id"] and c.get("kind") == kind), None)
        if "script" in st:  # the script is the route: the item's own route failing (unusable, broken) does not apply
            return it
        if c and c.get("status") in ("unusable", "hidden"):
            issues.append(f"{where}: card status is {c['status']}: {c.get('summary', '')[:120]}")
        if c and (c.get("verified") or {}).get("verdict") == "broken":
            issues.append(f"{where}: its render test failed: {(c.get('verified') or {}).get('note', '')}")
        return it

    for i, st in enumerate(plan["steps"], 1):
        app, kind = st.get("app", app0), st.get("kind")
        subs = st.get("effects") or [st]
        where = f"step {i} {st.get('name') or st.get('id') or ' + '.join(str(s.get('name') or s.get('id')) for s in subs)}"
        if app not in APPS or not kind:
            issues.append(f"{where}: needs app (PS / AI / CDR) and kind")
            continue
        if inp and app0 in APPS and app != app0:
            issues.append(f"{where}: a {app0} plan runs only {app0} steps; this {app} step would be skipped as manual")
        if "effects" in st and kind != "ps_layer_style":
            issues.append(f"{where}: \"effects\" (one combined layerEffects set) is for ps_layer_style steps only")
        its = [x for x in (item(app, kind, s, f"step {i} {s.get('name') or s.get('id')}") for s in subs) if x]
        seen = set()
        for x in its:
            if x["id"] in seen and not (x.get("extra") or {}).get("multi_key"):
                issues.append(f"{where}: a layer takes only one {x['name']} (it has no multi key), the repeat replaces it")
            seen.add(x["id"])
        if kind == "ps_layer_style" and len(subs) == len(its):
            issues += _shadow_under_stroke(where, list(zip(subs, its)))
        if "script" in st and not (isinstance(st["script"], str) and st["script"].strip()):
            issues.append(f"{where}: \"script\" must be the step's source code (a non-empty string)")
        if "target" in st:
            t = st["target"]
            if labels is not None and t not in labels:
                issues.append(f"{where}: target {t!r} is not a label: the input names {sorted(input_labels(app0, inp))}, "
                              "a step names what it leaves active with \"as\"")
            target = alias.get(t, t)
        if any(_whole_style(kind, x) for x in its):
            if target in styled:
                issues.append(f"{where}: replaces the whole style that step {styled[target]} gave the same target, so a "
                              f"step-by-step run keeps only this one: {_FIX.get(app, 'put it on another target')}")
            styled[target] = i
        elif its and kind == "ai_effect":
            styled[target] = i  # live effects add to the appearance; a later graphic style would replace them
        paths = [x.get("path") or "" for x in its]
        if any(p.startswith(_UNSTYLE) for p in paths):
            styled.pop(target, None)
        elif any(p.startswith(_RETARGET) and p != "Layer/New/Layer from Background" for p in paths):
            target = ("made by step", i)
        if st.get("as"):
            if labels is not None:
                labels.add(st["as"])
            # a script may leave a new layer / shape active (a duplicate ...): its "as" names something new
            alias[st["as"]] = ("script result", i) if "script" in st else target
        for extra in st.get("labels") or []:  # labels a script step adds itself (labels['bar'] = shape)
            if labels is not None:
                labels.add(extra)
            alias[extra] = ("made by step", i, extra)
        if "labels" in st and "script" not in st:
            issues.append(f"{where}: \"labels\" lists what a script adds; this step has no script")
        elif "labels" in st and app != "CDR":
            issues.append(f"{where}: \"labels\" is CorelDRAW-only (a CDR script sets labels[...]); in PS / AI end the "
                          "script on the new layer / object and name it with \"as\"")
    return issues


def stats():
    cc = Counter(c.get("kind") for c in cards())
    vd = Counter((c.get("verified") or {}).get("verdict") for c in cards() if c.get("verified"))
    return {"harvest": {f"{a}:{k}": len(v) for (a, k), v in sorted(harvest().items())}, "cards": dict(sorted(cc.items())),
            "verdicts": dict(vd)}


CMDS = ("find", "card", "equiv", "items", "check", "stats")


def _usage(msg):
    print(f"pgd.py: {msg} (python pgd.py --help)", file=sys.stderr)
    return 2


def _need(*dirs):
    """None when HERE has every one of these data folders, else the usage error (exit 2)"""
    miss = [d for d in dirs if not (HERE / d).is_dir()]
    return _usage(f"PGD_HOME {HERE} has no {' or '.join(d + '/' for d in miss)} folder: set PGD_HOME to a PGD data "
                  "folder") if miss else None


def _warn_unreadable():
    for f in unreadable():
        print(f"pgd.py: {f} is unreadable; its items are missing from this answer", file=sys.stderr)


def _main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd not in CMDS:
        return _usage(f"unknown command {cmd!r}; commands: {', '.join(CMDS)}")
    if cmd != "stats" and not rest:
        return _usage(f"{cmd} needs an argument")
    if cmd == "find":
        if _need("cards"):
            return 2
        kinds = {c.get("kind") for c in cards()}
        words, app, kind = list(rest), None, None
        while len(words) > 1 and (not app and words[-1].upper() in APPS or not kind and words[-1] in kinds):
            if not app and words[-1].upper() in APPS:
                app = words.pop().upper()
            else:
                kind = words.pop()
        w = words[-1].lower() if len(words) > 1 else ""  # a trailing app / kind word that did not peel is a typo
        if w in ("photoshop", "illustrator", "coreldraw", "corel") or (
                "_" in w and w.split("_")[0].upper() in APPS and words[-1] not in kinds):
            return _usage(f"unknown app or kind {words[-1]!r}: apps are {', '.join(APPS)}, kinds such as ps_filter")
        _warn_unreadable()
        for c in find(" ".join(words), app, kind):
            v = (c.get("verified") or {}).get("verdict", "")
            print(f"[{c.get('app')} {c.get('kind')}{' ' + v if v else ''}] {c.get('name')}: {(c.get('summary') or '')[:110]}")
    elif cmd in ("card", "equiv"):
        if len(rest) > 2:
            return _usage(f"{cmd} takes a name and an optional app: quote a name with spaces")
        app = rest[1].upper() if len(rest) == 2 else None
        if len(rest) == 2 and app not in APPS:
            return _usage(f"unknown app {rest[1]!r}: one of {', '.join(APPS)}")
        if _need("cards"):
            return 2
        _warn_unreadable()
        if cmd == "equiv":
            print(json.dumps(equiv(rest[0], app), indent=1, ensure_ascii=False))
            return 0
        c = card(rest[0], app)
        if c is None and app and card(rest[0]):
            others = sorted({x for x in APPS if card(rest[0], x)})
            print(f"pgd.py: no {app} card named {rest[0]!r}; other apps have one: {', '.join(others)}", file=sys.stderr)
        print(json.dumps(c, indent=1, ensure_ascii=False))
    elif cmd == "items":
        if rest[0].upper() not in APPS:
            return _usage(f"items takes an app first ({', '.join(APPS)}), got {rest[0]!r}")
        if _need("harvest"):
            return 2
        _warn_unreadable()
        print("\n".join(items(rest[0].upper(), " ".join(rest[1:]))))
    elif cmd == "check":
        if len(rest) != 1:
            return _usage("check takes one plan file")
        try:
            plan = json.loads(Path(rest[0]).read_bytes())  # UTF-8 (with or without a BOM) or UTF-16 / 32
        except (OSError, ValueError) as e:
            print(f"pgd.py check: cannot read {rest[0]} as JSON: {e}", file=sys.stderr)
            return 2
        if isinstance(plan, dict) and plan.get("steps") and _need("cards", "harvest"):
            return 2
        issues = check_plan(plan)
        if isinstance(plan, dict) and plan.get("steps") == []:
            issues.append('plan: "steps" is empty: there is nothing to check')
        print("\n".join(issues) or "OK: nothing PGD objects to")
        return 1 if issues else 0
    elif cmd == "stats":
        if not (HERE / "cards").is_dir() and not (HERE / "harvest").is_dir():
            return _need("cards", "harvest")
        _warn_unreadable()
        print(json.dumps(stats(), indent=1))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):  # Python 3.7+; a cp1252 console cannot encode Devanagari / Arabic summaries
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(_main(sys.argv[1:]))
