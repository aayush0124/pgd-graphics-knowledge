"""PGD: generate PGD.md (the readable guide) from the cards, the harvest and the verification results.

    python build_docs.py [OUT]        default PGD.md next to cards/
"""
import json, os, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parent)
KIND_TITLES = [
    ("ps_filter", "Photoshop filters"), ("ps_adjustment", "Photoshop adjustments"),
    ("ps_layer_style", "Photoshop layer styles"), ("ps_blend_mode", "Photoshop blend modes"),
    ("ps_tool", "Photoshop tools"), ("ps_menu", "Photoshop menu commands"), ("ps_preset", "Photoshop presets"),
    ("ps_api", "Photoshop scripting"),
    ("ai_effect", "Illustrator effects"), ("ai_blend_mode", "Illustrator blend modes"), ("ai_tool", "Illustrator tools"),
    ("ai_menu", "Illustrator menu commands"), ("ai_preset", "Illustrator presets"), ("ai_api", "Illustrator scripting"),
    ("cdr_effect", "CorelDRAW effects"), ("cdr_tool", "CorelDRAW tools"), ("cdr_menu", "CorelDRAW menu commands"),
    ("cdr_preset", "CorelDRAW presets"), ("cdr_api", "CorelDRAW scripting"),
    ("recipe", "Recipes (verified looks built from the cards)")]

HEAD = """# PGD: professional graphics designer knowledge base

PGD is what the design systems know about **Photoshop 2026**, **Illustrator 2026** and **CorelDRAW 2024**. Every item
below was harvested from the installed apps and their install folders (names, ids, menu paths, every parameter with its
type, default and range where the app states one), written up as a knowledge card, checked by a validator against that
harvest, reviewed by an adversarial agent, and (for effects, filters, adjustments, styles and blend modes) rendered on a
test plate and judged against the frame. Sibling of PVE (After Effects + Premiere).

## Using it

```
python pgd.py find "neon glow" [PS|AI|CDR]   # search by look / use
python pgd.py card "Gaussian Blur" PS          # one full card
python pgd.py equiv "Gaussian Blur"            # the same thing in the other apps
python pgd.py items CDR "contour"              # raw harvest search (names, ids, paths)
python pgd.py check plan.json                  # pre-flight a plan of steps
```

Plan format: `{"app": "PS", "steps": [{"kind": "ps_filter", "name": "Gaussian Blur", "settings": {"Radius": 12}}]}`
(names or harvest ids; settings by param name or key; several layer effects on one layer go in ONE step,
`{"kind": "ps_layer_style", "effects": [{"name": "Stroke", ...}, {"name": "Drop Shadow", ...}]}`, because each layer-style
step replaces the whole style; a step may name its `"target"` layer / object). In code:
`sys.path.insert(0, "<path to PGD>"); import pgd`.

`python run_plan.py run <recipe> PS|AI|CDR` runs a recipe's plan step by step in the live app on a known input
document and records what each step did (README "Running plans in the apps"). Each recipe below lists its plan runs:
complete (every step ran), partial (manual steps skipped), failed, or not run (no run of the plan as it is now), with
the judge's verdict on the result frame.

Status legend: **current**, obsolete (use the equivalent), hidden, needs_input (needs a selection, path, text, second
image ...), unusable. Verification: [v] matched its render; [wrong] the original card disagreed with its render and was
rewritten from the render; [weak] shows too faintly at the tested values; [broken] nothing rendered (often a test limit:
see the card's `verified.note`). Blank = not rendered (tools, menus, presets, scripting).

Files: `harvest/` raw ground truth (`CONTRACT.md` has the format); `cards/` knowledge cards; `gallery/` render test
frames; `cards/recipe_*.json` combined looks; `cards/zz_critic.json` known gaps.
"""


def load():
    cards = []
    for f in sorted((HERE / "cards").glob("*.json")):
        try:
            cards += json.loads(f.read_text(encoding="utf-8")).get("cards", [])
        except Exception:  # noqa: BLE001
            print("unreadable:", f.name)
    return cards


def runs(c):
    """a recipe's plan runs: ' Runs: PS complete [v], CDR partial, AI not run.' (a run of an older plan version is
    'not run'; the verdict is shown when it judged the current run)"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from run_plan import plan_hash
    out = []
    for app, p in sorted((c.get("plans") or {}).items()):
        h, r, v = plan_hash(p), p.get("run") or {}, p.get("verified") or {}
        if r.get("plan_hash") != h:
            out.append(f"{app} not run")
            continue
        vd = v.get("verdict") if v.get("plan_hash") == h else None
        out.append(f"{app} {r.get('result')}" + (" [v]" if vd == "pass" else f" [{vd}]" if vd else ""))
    return f" Runs: {', '.join(out)}." if out else ""


def line(c):
    vd = (c.get("verified") or {}).get("verdict")
    v = " [v]" if vd == "pass" else f" [{vd}]" if vd in ("weak", "wrong", "broken") else ""
    st = "" if c.get("status") in (None, "current") else f" *({c['status']})*"
    eq = ", ".join(f"{a}: {n}" for a, n in (c.get("equivalents") or {}).items() if n)
    run = runs(c) if c.get("kind") == "recipe" else ""
    return f"- **{c.get('name')}**{st}{v}: {(c.get('summary') or '').strip()}{f' (= {eq})' if eq else ''}{run}"


def anchor(t):
    return t.lower().replace(" ", "-").replace("(", "").replace(")", "")


def main(dest=None):
    cards = load()
    by = defaultdict(list)
    for c in cards:
        by[c.get("kind")].append(c)
    out = [HEAD, "## Contents\n"]
    out += [f"- [{t}](#{anchor(t)}) ({len(by[k])})" for k, t in KIND_TITLES if by.get(k)]
    for k, title in KIND_TITLES:
        if not by.get(k):
            continue
        out.append(f"\n## {title}\n")
        groups = defaultdict(list)
        for c in by[k]:
            groups[c.get("family") or c.get("category") or (c.get("path") or "").rsplit("/", 1)[0] or "Other"].append(c)
        for g in sorted(groups, key=str.lower):
            out.append(f"\n### {g}\n")
            out += [line(c) for c in sorted(groups[g], key=lambda c: (c.get("status") != "current", c.get("name") or ""))]
    critic = HERE / "cards" / "zz_critic.json"
    if critic.exists():
        z = json.loads(critic.read_text(encoding="utf-8"))
        out.append("\n## Known gaps (completeness critic)\n")
        for key in ("gaps", "weak_cards", "doubtful", "next_steps"):
            if z.get(key):
                out.append(f"\n### {key.replace('_', ' ').capitalize()}\n")
                out += [f"- {x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)}" for x in z[key]]
    dest = Path(dest or HERE / "PGD.md")
    dest.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"{dest.name}: {len(cards)} cards")


if __name__ == "__main__":
    main(*sys.argv[1:2])
