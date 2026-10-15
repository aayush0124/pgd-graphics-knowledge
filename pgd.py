"""PGD ("professional graphics designer"): what Photoshop 2026, Illustrator 2026 and CorelDRAW 2024 can do, harvested
from the installed apps, written up as knowledge cards and render-tested. Design systems read it to choose effects,
tools and presets, and to check a plan before anything is sent to an app.

    python pgd.py find "neon glow" [PS|AI|CDR] [kind]   search cards (name, summary, look, use_for)
    python pgd.py card "Gaussian Blur" [PS|AI|CDR]      one card in full (by name or id)
    python pgd.py equiv "Gaussian Blur"                 the same effect in the other two apps
    python pgd.py items AI "drop shadow"                search the raw harvest (names, ids, paths)
    python pgd.py check plan.json                       pre-flight a design plan (see check_plan)
    python pgd.py stats                                 what PGD knows

    import sys; sys.path.insert(0, "<path to PGD>"); import pgd
    pgd.find("halftone", app="PS"); pgd.check_plan(plan) -> [issues]

Data (cards/, harvest/) is read from $PGD_HOME when set, else from this file's folder.
"""
import json, os, re, sys
from functools import lru_cache
from pathlib import Path

CODE = Path(__file__).resolve().parent
HERE = Path(os.environ.get("PGD_HOME") or CODE)
APPS = ("PS", "AI", "CDR")
INPUT_DAMAGE = ("noise", "dust", "scratches", "jpeg", "blur", "haze", "tilt")  # run_plan.DAMAGE
# run_plan.py input plates -> the labels each names (a plan's "target" picks one; "as" adds more)
INPUT_LABELS = {"photo": ["photo"], "text": ["type", "background"], "blank": ["background"],
                "vector": ["art", "orange_box", "blue_star", "grad_circle", "pgd_type", "zigzag"]}


@lru_cache(None)
def cards():
    out = []
    for f in sorted((HERE / "cards").glob("*.json")):
        try:
            out += json.loads(f.read_text(encoding="utf-8")).get("cards", [])
        except Exception:  # noqa: BLE001  (a card file mid-write is skipped, not fatal)
            pass
    return out


@lru_cache(None)
def harvest():
    """(app, kind) -> {id: item}"""
    out = {}
    for f in sorted((HERE / "harvest").glob("*/*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        out[(d["app"], d["kind"])] = {it["id"]: it for it in d["items"]}
    return out


def _words(q):
    return [w for w in re.split(r"\W+", q.lower()) if w]


def find(query, app=None, kind=None, limit=25):
    """Rank cards by query words in name / look / summary / use_for (name hits weigh most); verified passes first."""
    words, scored = _words(query), []
    for c in cards():
        if app and c.get("app") != app or kind and c.get("kind") != kind:
            continue
        name = (c.get("name") or "").lower()
        hay = " ".join([name, " ".join(c.get("look") or []), c.get("summary") or "", " ".join(c.get("use_for") or []),
                        c.get("path") or ""]).lower()
        s = sum(3 * (w in name) + hay.count(w) for w in words)
        if s:
            s += (c.get("status") == "current") + ((c.get("verified") or {}).get("verdict") == "pass")
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:limit]]


def card(name, app=None):
    """By name, id or menu path (equivalents may hold any of the three)."""
    n = name.lower()
    hit = [c for c in cards() if n in ((c.get("name") or "").lower(), (c.get("id") or "").lower(), (c.get("path") or "").lower())]
    if app:
        hit = [c for c in hit if c.get("app") == app] or hit
    hit.sort(key=lambda c: (c.get("status") != "current", c.get("kind", "").endswith("_menu")))
    return hit[0] if hit else None


def equiv(name):
    """The card for `name` plus the cards its equivalents point at (and cards in other apps that point back)."""
    c = card(name)
    if not c:
        return {}
    out = {c["app"]: f"{c['name']} [{c['kind']} {c['id']}]"}
    for app, other in (c.get("equivalents") or {}).items():
        o = other and card(other, app)
        if o:
            out[app] = f"{o['name']} [{o['kind']} {o['id']}]"
        elif other:
            out[app] = f"{other} (no card)"
    mine = {c["name"].lower(), c["id"].lower(), (c.get("path") or "").lower()} - {""}
    for o in cards():
        back = ((o.get("equivalents") or {}).get(c["app"]) or "").lower()
        if o.get("app") not in out and back and back in mine:
            out[o["app"]] = f"{o['name']} [{o['kind']} {o['id']}]"
    return out


def items(app, query, limit=40):
    words, res = _words(query), []
    for (a, kind), its in harvest().items():
        if a != app:
            continue
        for it in its.values():
            hay = " ".join(str(it.get(k, "")) for k in ("name", "id", "path", "category")).lower()
            if all(w in hay for w in words):
                res.append(f"[{kind}] {it['name']}  id={it['id']}  path={it.get('path', '')}")
    return res[:limit]


def _lookup(app, kind, step):
    its = harvest().get((app, kind)) or {}
    if step.get("id") in its:
        return its[step["id"]]
    n = (step.get("name") or "").lower()
    hit = [it for it in its.values() if it["name"].lower() == n or (it.get("path") or "").lower() == n]
    return hit[0] if len(hit) == 1 else (hit or None)


def _whole_style(kind, it):
    """Steps that replace the target's style instead of adding to it: a ps_layer_style step writes the layer's whole
    layerEffects set (a Styles preset too), an Illustrator graphic style (applyTo) replaces the appearance."""
    return kind == "ps_layer_style" or kind.endswith("_preset") and it.get("category") in ("Layer style", "Graphic Style")


# After these the next step acts on another layer / object, or on one whose style is baked into pixels / paths.
_RETARGET = ("Layer/New/", "Layer/New Fill Layer/", "Layer/New Adjustment Layer/", "Layer/Duplicate Layer",
             "Layer/Group Layers", "Layer/Merge", "Layer/Flatten Image", "Layer/Smart Objects/Convert to Smart Object",
             "Layer/Smart Objects/New Smart Object via Copy", "Layer/Rasterize/Layer Style", "File/Place", "Edit/Paste",
             "Object/Group", "Object/Expand")
_FIX = {"PS": "merge the layer effects into one ps_layer_style step with \"effects\", or move this one to another layer "
              "(Duplicate Layer, a new layer, a \"target\")",
        "AI": "apply the graphic style first and the live effects after it, or put it on another object (Paste in Front, "
              "Group, a \"target\")"}


def missing_required(it, settings):
    """CorelDRAW object-model calls (cdr_com Shape.Create*) take positional arguments: the params with no harvested
    default (colours / objects excepted, they may be None) that `settings` leaves out, which the call cannot get."""
    inv = (it.get("invoke") or {}).get("cdr_com") or ""
    if not inv or (it.get("extra") or {}).get("effect_id"):
        return []
    have = set(settings or {})
    return [p["key"] for p in it.get("params") or [] if p.get("default") is None
            and p.get("type") not in ("color", "object") and p["key"] not in have and p["name"] not in have
            and not (p["key"] == "Type" and (it.get("extra") or {}).get("lens_type") is not None)
            and not (p["key"] in ("OriginX", "OriginY") and "Distortion" in inv)]


def _setting(sub, it, key):
    """a layer-effect value from the step's settings (by key or param name), else the harvested default"""
    p = next((p for p in it.get("params") or [] if p.get("key") == key), {})
    s = sub.get("settings") or {}
    return s.get(key, s.get(p.get("name"), p.get("default")))


def _shadow_under_stroke(where, pairs):
    """a Drop Shadow that moves no further than an outside / centred Stroke on the same layer reaches is drawn under
    the stroke and never shows (plan runs 2026-10-15: four Photoshop plans lost their shadow this way)"""
    reach = [(_setting(s, it, "size") or 0) / (1 if _setting(s, it, "style") == "outsetFrame" else 2)
             for s, it in pairs if it["id"] == "frameFX" and _setting(s, it, "style") in ("outsetFrame", "centeredFrame")]
    out = []
    for s, it in pairs:
        if it["id"] == "dropShadow" and reach:
            d = _setting(s, it, "distance") or 0
            if d <= max(reach):
                out.append(f"{where}: Drop Shadow distance {d:g} px does not reach past the {max(reach):g} px the "
                           "outside Stroke covers, so the shadow is hidden under the stroke: make the distance larger "
                           "than the stroke size (or move the stroke inside)")
    return out


def check_plan(plan):
    """Pre-flight a design plan: {"app": "PS", "steps": [{"kind": "ps_filter", "name" | "id": ..., "settings": {...}}]}
    (a step may carry its own "app"). Flags unknown items, ambiguous names, unknown params, wrong types, out-of-range
    values, CorelDRAW object-model calls missing a param that has no default, and items whose card says they are not
    usable or whose render test failed.

    A step acts on the active layer / selection, or on the one its optional "target" names ("target": "type layer");
    items that make or switch layers / objects (Duplicate Layer, fill and adjustment layers, Layer Via Copy, Merge,
    Paste, Group, Expand Appearance ...) move the active one. A whole-style step replaces the style instead of adding to
    it (a ps_layer_style step writes the layer's whole layerEffects set, so does a Styles preset; an Illustrator graphic
    style replaces the appearance, live effects included), so a second one on the same target is flagged: a step-by-step
    run would keep only the last. Several effects on one layer go in ONE step, sent as one layerEffects descriptor:
    {"kind": "ps_layer_style", "effects": [{"name": "Stroke", "settings": {...}}, {"name": "Drop Shadow", ...}]}
    (an effect repeated there goes in its multi list, e.g. dropShadowMulti; one without a multi key is flagged).

    Runnable plans (run_plan.py) also carry "input" (the document they start from: {"plate": "photo" | "text" |
    "vector" | "blank", ...}); then every "target" must be a label: one the input names (INPUT_LABELS, + "type" when
    the input has "text") or one an earlier step gave what it left active with "as", or one a script step lists in
    "labels" (the labels its script adds). A "script" is the step's own source code (ExtendScript for PS / AI, Python
    for CDR), run instead of the item's route, so the item's required values are not asked of it."""
    sys.path.insert(0, str(CODE))
    from validate_cards import check_value, param_index  # one implementation of the value rules
    issues, target, styled = [], None, {}  # styled: target -> last step that set its whole style / appearance
    inp, alias, labels = plan.get("input") or {}, {}, None  # alias: an "as" label -> the target it names
    plate = inp.get("plate")
    if inp:
        if plate not in INPUT_LABELS:
            issues.append(f"input: plate {plate!r} is not one of {sorted(INPUT_LABELS)}")
        labels = set(INPUT_LABELS.get(plate, [])) | ({"type"} if inp.get("text") else set())
        dmg = inp.get("damage")
        if dmg is not None:
            if plate != "photo" or not isinstance(dmg, dict):
                issues.append('input: "damage" is a dict on the photo plate ({"noise": 12, "dust": 80, ...})')
            else:
                for k, v in dmg.items():
                    if k not in INPUT_DAMAGE:
                        issues.append(f"input: damage {k!r} is not one of {sorted(INPUT_DAMAGE)}")
                    elif not isinstance(v, (int, float)) or isinstance(v, bool) or (v < 0 and k != "tilt"):
                        issues.append(f"input: damage {k} must be a number >= 0 (tilt may be negative), got {v!r}")

    def item(app, kind, st, where):
        it = _lookup(app, kind, st)
        if it is None:
            issues.append(f"{where}: no {app} {kind} by that name or id (search: python pgd.py items {app} \"...\")")
            return None
        if isinstance(it, list):
            issues.append(f"{where}: name is ambiguous in {app} {kind}: use an id from {[x['id'] for x in it][:6]}")
            return None
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
            issues.append(f"{where}: {it['name']} needs {', '.join(miss)} (no default; the call takes them positionally)")
        c = next((c for c in cards() if c.get("id") == it["id"] and c.get("kind") == kind), None)
        if "script" in st:  # the script is the route: the item's own route failing (unusable, broken) does not apply
            return it
        if c and c.get("status") in ("unusable", "hidden"):
            issues.append(f"{where}: card status is {c['status']}: {c.get('summary', '')[:120]}")
        if c and (c.get("verified") or {}).get("verdict") == "broken":
            issues.append(f"{where}: its render test failed: {(c.get('verified') or {}).get('note', '')}")
        return it

    for i, st in enumerate(plan.get("steps", []), 1):
        app, kind = st.get("app", plan.get("app")), st.get("kind")
        subs = st.get("effects") or [st]
        where = f"step {i} {st.get('name') or st.get('id') or ' + '.join(str(s.get('name') or s.get('id')) for s in subs)}"
        if app not in APPS or not kind:
            issues.append(f"{where}: needs app (PS / AI / CDR) and kind")
            continue
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
            t = str(st["target"])
            if labels is not None and t not in labels:
                issues.append(f"{where}: target {t!r} is not a label: the input names {sorted(INPUT_LABELS.get(plate, []))}"
                              f"{' + type' if inp.get('text') else ''}, a step names what it leaves active with \"as\"")
            target = alias.get(t, t)
        if any(_whole_style(kind, x) for x in its):
            if target in styled:
                issues.append(f"{where}: replaces the whole style that step {styled[target]} gave the same target, so a "
                              f"step-by-step run keeps only this one: {_FIX.get(app, 'put it on another target')}")
            styled[target] = i
        elif its and kind == "ai_effect":
            styled[target] = i  # live effects add to the appearance; a later graphic style would replace them
        if any((x.get("path") or "").startswith(_RETARGET) and x.get("path") != "Layer/New/Layer from Background"
               for x in its):
            target = ("made by step", i)
        if st.get("as"):
            if labels is not None:
                labels.add(str(st["as"]))
            alias[str(st["as"])] = target
        for extra in st.get("labels") or []:  # labels a script step adds itself (labels['bar'] = shape)
            if labels is not None:
                labels.add(str(extra))
            alias[str(extra)] = ("made by step", i, str(extra))
        if "labels" in st and "script" not in st:
            issues.append(f"{where}: \"labels\" lists what a script adds; this step has no script")
    return issues


def stats():
    from collections import Counter
    cc = Counter(c.get("kind") for c in cards())
    vd = Counter((c.get("verified") or {}).get("verdict") for c in cards() if c.get("verified"))
    return {"harvest": {f"{a}:{k}": len(v) for (a, k), v in sorted(harvest().items())}, "cards": dict(sorted(cc.items())),
            "verdicts": dict(vd)}


def _main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    app = next((a for a in rest[1:] if a in APPS), None)
    if cmd == "find":
        kind = next((a for a in rest[1:] if "_" in a), None)
        for c in find(rest[0], app, kind):
            v = (c.get("verified") or {}).get("verdict", "")
            print(f"[{c.get('app')} {c.get('kind')}{' ' + v if v else ''}] {c.get('name')}: {(c.get('summary') or '')[:110]}")
    elif cmd == "card":
        print(json.dumps(card(rest[0], app), indent=1, ensure_ascii=False))
    elif cmd == "equiv":
        print(json.dumps(equiv(rest[0]), indent=1, ensure_ascii=False))
    elif cmd == "items":
        print("\n".join(items(rest[0], " ".join(rest[1:]))))
    elif cmd == "check":
        issues = check_plan(json.loads(Path(rest[0]).read_text(encoding="utf-8")))
        print("\n".join(issues) or "OK: nothing PGD objects to")
        return 1 if issues else 0
    elif cmd == "stats":
        print(json.dumps(stats(), indent=1))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):  # Python 3.7+; a cp1252 console cannot encode Devanagari / Arabic summaries
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(_main(sys.argv[1:]))
