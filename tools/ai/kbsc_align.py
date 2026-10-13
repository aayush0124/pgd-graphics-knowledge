"""PGD / Illustrator: pair Illustrator Defaults.kys ids with the display names of the Keyboard Shortcuts dialog.

    python kbsc_align.py        -> work/ai/kbsc/align.json (+ align_report.txt)

Inputs (all from the installed app):
  work/ai/kbsc/kbsc_export_menus.txt  Edit > Keyboard Shortcuts > Export Text... (kbsc_export.py): every Tool and Menu
                                      Command of the dialog, in dialog order, with its shortcut. Submenu names appear as
                                      lines of their own (no indentation); menu commands carry the shortcut glued to the
                                      name ("NewCtrl+N"), tools carry it after a tab.
  work/ai/menu_<Top>.json             live menu walk (menu_walk.py): tells which export lines are submenu headers and
                                      gives each command its menu path
  Illustrator Defaults.kys            /Menus and /Tools ids with default keys. The file lists the ids in (roughly) the
                                      REVERSE of the dialog order, so the alignment runs on the reversed id list.
  work/ai/tools_stage/pool.json       internal names stored next to each id in the binaries (ai_menus.py pool)

Two global alignments (Needleman-Wunsch, no crossings):
  1. export menu lines  x  walked menu nodes (DFS order)   score: same name (show/hide-tolerant) + same shortcut
  2. export commands    x  reversed kys ids                score: same shortcut (strong), id words explained by the
                                                            dialog name / its submenu, internal name equal
Then unpaired leftovers are paired by unique shortcut, then by unique full word match.
Each pair records its evidence: shortcut / words / table / order (order = nothing but its place between neighbours).
"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_menus import KYS, STAGE, WORK, read_kys, key_name  # noqa: E402

KB = WORK / "kbsc"
EXPORT = KB / "kbsc_export_menus.txt"
TOPS = ["File", "Edit", "Object", "Type", "Select", "Effect", "View", "Window", "Help"]
OTHER = ["Other Select", "Other Text", "Other Object", "Other Panel", "Other Misc"]
SHIFTED = dict(zip('"<>{}+~_:?|!@#$%^&*()', "',.[]=`-;/\\1234567890"))
SC_RE = re.compile(r"^(.*?)\s*((?:(?:Alt|Shift|Ctrl)\+)+(?:F\d{1,2}|Tab|Space|.)|F\d{1,2})$")


# ------------------------------------------------------------------ shortcuts
def sc_key(s):
    """'Shift+Ctrl+b' / 'Ctrl+Shift+B' / 'Ctrl+"' vs "Ctrl+'" -> one canonical form (unshifted key, sorted mods)."""
    if not s:
        return ""
    s = s.strip()
    if s.endswith("++"):
        mods, key = s[:-2].split("+"), "+"
    elif "+" in s:
        parts = s.split("+")
        mods, key = parts[:-1], parts[-1]
    else:
        mods, key = [], s
    mods = [m for m in mods if m]
    key = SHIFTED.get(key, key).upper()
    return "+".join(sorted(mods) + [key])


def kys_keys(k):
    """canonical shortcut variants of a kys entry: built from /Represent and from /Key (the dialog shows either)."""
    out = set()
    if not k["key"]:
        return out
    m = [n for b, n in ((128, "Alt"), (32, "Shift"), (64, "Ctrl")) if k["mods"] & b]
    for code in (k["rep"], k["key"]):
        kn = key_name(code)
        if kn:
            out.add(sc_key("+".join(m + [kn])))
    return out


# ------------------------------------------------------------------ export
def parse_export():
    lines = EXPORT.read_text(encoding="utf-8-sig").splitlines()
    i_tools, i_menus = lines.index("Tools"), lines.index("Menu Commands")
    tools = []
    for ln in lines[i_tools + 1:i_menus]:
        if ln.strip():
            name, _, sc = ln.partition("\t")
            tools.append({"name": name.strip(), "sc": sc.strip()})
    menus = []
    for ln in lines[i_menus + 1:]:
        if not ln.strip():
            continue
        m = SC_RE.match(ln)
        name, sc = (m.group(1), m.group(2)) if m and m.group(1).strip() else (ln, "")
        menus.append({"name": name.strip(), "sc": sc.strip(), "raw": ln})
    return tools, menus


# ------------------------------------------------------------------ text
SYN = {"hide": "show", "unlock": "lock", "global": "artboard", "pref": "preferenc", "prefs": "preferenc"}
STOPW = {"adobe", "ai", "menu", "item", "the", "a", "on", "to", "of", "and", "plugin", "plug", "in", "palette",
         "dialog", "shortcut", "command", "window", "with", "for", "tool", "psadapter", "live"}


def toks(x, stop=STOPW):
    x = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", re.sub(r"([a-z])([A-Z])", r"\1 \2", x))
    x = re.sub(r"(?<![0-9])-(?=[0-9])", " negative ", x)
    out = set()
    for t in re.findall(r"[a-z]+|[0-9]+", x.lower()):
        t = SYN.get(t, t)
        if t in stop:
            continue
        out.add(re.sub(r"(ing|es|s|e)$", "", t) if len(t) > 4 else t)
    return out


def nname(s):
    return re.sub(r"[^a-z0-9]+", "", s.replace("...", "").replace("…", "").replace("&", "").lower())


# ------------------------------------------------------------------ NW
def nw(a, b, score, gap=-1.0):
    n, m = len(a), len(b)
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    P = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        S[i][0], P[i][0] = i * gap, 1
    for j in range(1, m + 1):
        S[0][j], P[0][j] = j * gap, 2
    for i in range(1, n + 1):
        ai, Si, Sp = a[i - 1], S[i], S[i - 1]
        for j in range(1, m + 1):
            d = Sp[j - 1] + score(ai, b[j - 1])
            u = Sp[j] + gap
            l = Si[j - 1] + gap
            if d >= u and d >= l:
                Si[j], P[i][j] = d, 0
            elif u >= l:
                Si[j], P[i][j] = u, 1
            else:
                Si[j], P[i][j] = l, 2
    pairs, i, j = [], n, m
    while i > 0 or j > 0:
        p = P[i][j]
        if i > 0 and j > 0 and p == 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and (j == 0 or p == 1):
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


# ------------------------------------------------------------------ 1: export lines x walked nodes
def walked_nodes():
    out = []

    def rec(tree, path):
        for n in tree:
            if "name" not in n or not n["name"].strip():
                continue
            p = f"{path}/{n['name']}"
            out.append({"name": n["name"], "path": p, "header": bool(n.get("children")), "sc": n.get("shortcut", ""),
                        "cmd": n.get("cmd_id")})
            if n.get("children"):
                rec(n["children"], p)
    for t in TOPS:
        out.append({"name": t, "path": t, "header": True, "sc": "", "top": True})
        rec(json.loads((WORK / f"menu_{t}.json").read_text(encoding="utf-8")), t)
    return out


def name_score(e, w):
    a, b = nname(e["name"]), nname(w["name"])
    if not a or not b:
        return -3
    s = -3.0
    if a == b:
        s = 5.0
    else:
        ta, tb = toks(e["name"], set()), toks(w["name"], set())
        if ta and ta == tb:
            s = 4.0
        elif len(a) >= 5 and (a.startswith(b) or b.startswith(a)):
            s = 2.5
        elif ta and tb and len(ta & tb) / len(ta | tb) >= 0.5:
            s = 1.0
    if e["sc"] and w["sc"]:
        s += 3 if sc_key(e["sc"]) == sc_key(w["sc"]) else -2
    return s


def align_walked(menus):
    nodes = walked_nodes()
    # 'Other ...' sections are not on the menu bar
    cut = next(i for i, e in enumerate(menus) if e["name"] == OTHER[0] and i > len(menus) // 2)
    pairs = nw(menus[:cut], nodes, name_score, gap=-1.0)
    for i, j in pairs:
        if name_score(menus[i], nodes[j]) > 0:
            menus[i]["walked"] = nodes[j]
    # path + header flag for every export line
    sec, stack = None, []
    for i, e in enumerate(menus):
        w = e.get("walked")
        if i >= cut:
            if e["name"] in OTHER:
                e["header"], e["path"], sec = True, e["name"], e["name"]
            else:
                e["header"], e["path"] = False, f"{sec}/{e['name']}"
            e["section"] = sec
            continue
        if w:
            e["header"], e["path"] = w["header"], w["path"]
            e["path_from"] = "walked menu"
        else:
            # not on the walked menu bar (state-dependent label, hidden item): place it after the previous line
            prev = next((menus[k] for k in range(i - 1, -1, -1) if menus[k].get("walked")), None)
            parent = prev["path"] if prev and prev["header"] else (prev["path"].rsplit("/", 1)[0] if prev else "")
            e["header"], e["path"] = False, f"{parent}/{e['name']}"
            e["path_from"] = "export order (not on the walked menu bar)"
        e["section"] = e["path"].split("/")[0]
    # an unwalked line followed by lines whose walked path runs through it is a header
    for i, e in enumerate(menus[:cut]):
        if not e.get("walked") and i + 1 < cut:
            nxt = menus[i + 1].get("walked")
            if nxt and nxt["path"].split("/")[-2:-1] == [e["name"]]:
                e["header"] = True
    return menus, cut


# ------------------------------------------------------------------ 2: export commands x reversed kys ids
def cand_names(pool, kid):
    names = set()
    for occ in pool.get(kid, []):
        for s in occ["prev"][-1:]:
            if not s.startswith("$$$/") and len(s) < 80:
                names.add(nname(s))
    return names


def make_ev(pool):
    cache = {}

    def kinfo(k):
        if k["id"] not in cache:
            raw = k["id"].lstrip("~")
            cache[k["id"]] = (kys_keys(k), toks(re.sub(r"\d+$", "", raw)), cand_names(pool, k["id"]), toks(raw))
        return cache[k["id"]]

    def ev(e, k):
        if "_t" not in e:
            segs = e["path"].split("/")
            tn0 = toks(segs[-1]) | toks(e["name"])  # walked label (state-dependent) + the dialog's own name
            e["_t"] = (sc_key(e["sc"]), tn0, toks(" ".join(segs)) | tn0, nname(e["name"]), toks(" ".join(segs[:-1])))
        es, tn, tp, nn, tpar = e["_t"]
        ks, tid, cn, tid_d = kinfo(k)
        if tn & tid_d - tid:  # a number in the label that the id also ends with: 'RotateView150' <- '150'
            tid = tid_d
        r = {}
        if es and ks:
            r["sc"] = 1 if es in ks else -1
            if r["sc"] == 1 and exact(e["sc"]) == exact_kys(k):  # the dialog shows /Key: '=' (zoomin) vs '+' (zoomin2)
                r["sc_exact"] = True
        elif es or ks:
            r["sc"] = 0
        if tid:
            own = tid - (tpar - tn)  # id words left once the submenu's words are taken out
            r["w_name"] = len(own & tn) / len(own | tn) if own | tn else 0.0
            r["w_path"] = len(tid & tp) / len(tid)
            nid = nname(k["id"])
            if r["w_name"] < 1 and len(tid) <= 1 and ((len(nn) >= 4 and nn in nid) or (len(nid) >= 4 and nid in nn)):
                # only for ids written as one lowercase run; a multi-word id must match by words  # 'transformrotate' <- 'Rotate'
                r["w_name"], r["w_path"] = 1.0, 1.0
                r["substr"] = True
        r["table"] = nn in cn
        return r
    return ev


def exact(s):
    s = s.strip()
    mods, key = (s[:-2].split("+"), "+") if s.endswith("++") else ((s.split("+")[:-1], s.split("+")[-1]) if "+" in s else ([], s))
    return "+".join(sorted(m for m in mods if m) + [key.upper()])


def exact_kys(k):
    m = [n for b, n in ((128, "Alt"), (32, "Shift"), (64, "Ctrl")) if k["mods"] & b]
    return exact("+".join(m + [key_name(k["key"])])) if k["key"] else ""


def pair_score(r):
    """+ same shortcut, + label words = the id's own words (submenu words taken out), + internal name equal;
    - different / one-sided shortcut (the export is the default set, so keys must agree), - id words the menu path
    does not explain."""
    s = -1.0
    sc = r.get("sc")
    if sc == 1:
        s += 8 + (3 if r.get("sc_exact") else 0)
    elif sc == -1:
        s -= 8
    elif sc == 0:
        s -= 5
    if "w_name" in r:
        s += 6 * r["w_name"] - 1.5 * (1 - r["w_path"])
    if r["table"]:
        s += 4
    return s


def evidence(r):
    return r.get("sc") == 1 or r["table"] or r.get("w_name", 0) >= 0.3


def sw_best(M, rows_free, cols, gap=-1.5):
    """best local alignment (Smith-Waterman) of free rows against the column order `cols` -> (score, [(i, col)])."""
    R = [i for i in range(len(M)) if rows_free[i]]
    n, m = len(R), len(cols)
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    P = [[0] * (m + 1) for _ in range(n + 1)]
    best, bi, bj = 0.0, 0, 0
    for a in range(1, n + 1):
        row, Sa, Sp, Pa = M[R[a - 1]], S[a], S[a - 1], P[a]
        for b in range(1, m + 1):
            c = cols[b - 1]
            d = Sp[b - 1] + row[c] if c >= 0 else -1e9
            u = Sp[b] + gap
            l = Sa[b - 1] + gap
            v = max(0.0, d, u, l)
            Sa[b] = v
            Pa[b] = 0 if v == 0 else (1 if v == d else (2 if v == u else 3))
            if v > best:
                best, bi, bj = v, a, b
    pairs, a, b = [], bi, bj
    while a > 0 and b > 0 and P[a][b]:
        p = P[a][b]
        if p == 1:
            pairs.append((R[a - 1], cols[b - 1]))
            a, b = a - 1, b - 1
        elif p == 2:
            a -= 1
        else:
            b -= 1
    return best, pairs[::-1]


def align_kys(cmds, kys, pool, min_block=7.0):
    """iterated local alignment: the kys file lists ids in blocks (one per registering plug-in), most of them in reverse
    dialog order, some forward, and the blocks themselves are not in dialog order. Each round takes the best-scoring
    block in either direction, then removes its rows and columns."""
    ev = make_ev(pool)
    E = [[ev(e, k) for k in kys] for e in cmds]
    M = [[pair_score(r) for r in row] for row in E]
    rows_free = [True] * len(cmds)
    col_free = [True] * len(kys)
    res = {}
    while True:
        fwd = [c for c in range(len(kys)) if col_free[c]]
        cands = [sw_best(M, rows_free, fwd), sw_best(M, rows_free, fwd[::-1])]
        best, pairs = max(cands, key=lambda x: x[0])
        if best < min_block or not pairs:
            break
        fr = [i for i in range(len(cmds)) if rows_free[i]]
        rev = pairs[0][1] > pairs[-1][1] if len(pairs) > 1 else False
        fc = [c for c in range(len(kys)) if col_free[c]]
        rpos = {i: n for n, i in enumerate(fr)}
        cpos = {c: (len(fc) - 1 - n if rev else n) for n, c in enumerate(fc)}
        strong = [evidence(E[i][c]) for i, c in pairs]
        keep = []
        for t, (i, c) in enumerate(pairs):
            if strong[t]:
                keep.append((i, c))
                continue
            # an order-only pair counts only inside a gap-free run between two evidence pairs of this block
            p = next((u for u in range(t - 1, -1, -1) if strong[u]), None)
            q = next((u for u in range(t + 1, len(pairs)) if strong[u]), None)
            if p is None or q is None:
                continue
            seg = pairs[p:q + 1]
            if all(rpos[seg[n + 1][0]] - rpos[seg[n][0]] == 1 and cpos[seg[n + 1][1]] - cpos[seg[n][1]] == 1
                   for n in range(len(seg) - 1)):
                keep.append((i, c))
        if not keep:
            break
        for i, c in keep:
            res[i] = (kys[c]["id"], dict(E[i][c], block=round(best, 1)))
            rows_free[i] = False
            col_free[c] = False
    # 2-opt: two pairs whose own evidence clearly prefers each other's id swap (a forward-ordered run of ids inside a
    # reversed block: RotateView180..RotateViewNegative180 had been paired mirror-wise)
    changed = True
    while changed:
        changed = False
        ids = {k["id"]: c for c, k in enumerate(kys)}
        rows = sorted(res)
        for x in rows:
            for y in rows:
                if y <= x:
                    continue
                cx, cy = ids[res[x][0]], ids[res[y][0]]
                wn = lambda i, c: E[i][c].get("w_name", 0)  # noqa: E731
                if M[x][cy] + M[y][cx] > M[x][cx] + M[y][cy] + 2 and min(M[x][cy], M[y][cx]) > 0 and                         min(wn(x, cy), wn(y, cx)) >= 0.5 and wn(x, cy) + wn(y, cx) >= wn(x, cx) + wn(y, cy) + 0.5:
                    res[x], res[y] = ((kys[cy]["id"], dict(E[x][cy], swapped=True)),
                                      (kys[cx]["id"], dict(E[y][cx], swapped=True)))
                    changed = True
    # leftovers: unique shortcut, then unique full word match
    left_e = [i for i in range(len(cmds)) if rows_free[i]]
    for i in left_e:
        ks = [c for c in range(len(kys)) if col_free[c] and E[i][c].get("sc") == 1]
        es = [x for x in left_e if rows_free[x] and any(E[x][c].get("sc") == 1 for c in ks)]
        if len(ks) == 1 and es == [i]:
            res[i] = (kys[ks[0]]["id"], dict(E[i][ks[0]], leftover=True))
            rows_free[i], col_free[ks[0]] = False, False
    for i in left_e:
        if not rows_free[i]:
            continue
        good = [c for c in range(len(kys)) if col_free[c] and E[i][c].get("w_name", 0) == 1 and E[i][c].get("sc") != -1]
        if len(good) == 1 and [x for x in left_e if rows_free[x] and E[x][good[0]].get("w_name", 0) == 1] == [i]:
            res[i] = (kys[good[0]]["id"], dict(E[i][good[0]], leftover=True))
            rows_free[i], col_free[good[0]] = False, False
    # last: an unpaired entry right after a run of two pairs whose ids are neighbours in the file takes the next id of
    # that run when it is free ('Path Eraser' after Pencil / Smooth = Adobe Freehand Erase Tool). Order only.
    pos = {k["id"]: c for c, k in enumerate(kys)}
    for i in range(2, len(cmds)):
        if i in res or (i - 1) not in res or (i - 2) not in res:
            continue
        cp, cp2 = pos[res[i - 1][0]], pos[res[i - 2][0]]
        if abs(cp - cp2) != 1:
            continue
        c = cp + (cp - cp2)
        chained = res[i - 1][1].get("adjacent")  # a chain of order-only steps drifts: the next step needs words
        if 0 <= c < len(kys) and col_free[c] and E[i][c].get("sc") != -1 and                 not (E[i][c].get("sc") == 0 and sc_key(cmds[i]["sc"])) and                 (not chained or E[i][c].get("w_name", 0) > 0):
            res[i] = (kys[c]["id"], dict(E[i][c], leftover=True, adjacent=True))
            col_free[c] = False
    return res


def classify(r):
    """evidence label of one pair."""
    if r.get("sc") == -1:
        return "conflict"
    parts = []
    if r.get("sc") == 1:
        parts.append("shortcut")
    if r.get("table"):
        parts.append("table")
    if r.get("w_name", 0) >= 0.999 or (r.get("w_path", 0) >= 0.999 and r.get("w_name", 0) > 0):
        parts.append("words")
    elif r.get("w_path", 0) > 0:
        parts.append("some-words")
    if not parts:
        parts.append("order")
    return "+".join(parts) + ("" if r.get("leftover") else "+order")


def main():
    KB.mkdir(parents=True, exist_ok=True)
    tools, menus = parse_export()
    menus, cut = align_walked(menus)
    pool = json.loads((STAGE / "pool.json").read_text(encoding="utf-8"))
    cmds = [e for e in menus if not e["header"]]
    kys = read_kys()
    res = align_kys(cmds, kys, pool)
    out = {"menus": [], "tools": []}
    for i, e in enumerate(cmds):
        rec = {"name": e["name"], "shortcut": e["sc"], "path": e["path"], "section": e["section"],
               "path_from": e.get("path_from", "keyboard shortcuts dialog section"),
               "walked_path": (e.get("walked") or {}).get("path")}
        if i in res:
            kid, r = res[i]
            rec.update(id=kid, how=classify(r), ev=r)
        out["menus"].append(rec)
    for e in cmds:
        e.pop("_t", None)
    out["headers"] = [e["path"] for e in menus if e["header"]]
    paired = {r.get("id") for r in out["menus"]}
    out["kys_not_in_dialog"] = [k["id"] for k in kys if k["id"] not in paired]

    # tools: the Tools section x reversed /Tools ids (tool names carry no submenu: path = section)
    tk = read_kys("Tools")
    tcmds = [dict(t, path=f"Tools/{t['name']}") for t in tools]
    tres = align_kys(tcmds, tk, pool)
    for i, t in enumerate(tools):
        rec = {"name": t["name"], "shortcut": t["sc"], "position": i}
        if i in tres:
            kid, r = tres[i]
            rec.update(id=kid, how=classify(r), ev=r)
        out["tools"].append(rec)
    tp = {r.get("id") for r in out["tools"]}
    out["tool_ids_not_in_dialog"] = [k["id"] for k in tk if k["id"] not in tp]
    (KB / "align.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    from collections import Counter
    rep = []
    for sec in ("menus", "tools"):
        c = Counter(r.get("how", "UNPAIRED") for r in out[sec])
        rep.append(f"{sec}: {len(out[sec])} dialog commands; {dict(c)}")
    rep.append(f"kys menu ids not in dialog: {len(out['kys_not_in_dialog'])}: {out['kys_not_in_dialog']}")
    rep.append(f"tool ids not in dialog: {out['tool_ids_not_in_dialog']}")
    for sec in ("menus", "tools"):
        for r in out[sec]:
            rep.append(f"{sec[0]} {r.get('how', 'UNPAIRED'):28s} {r.get('id', '-')!s:45s} <- {r.get('path', r['name'])} [{r['shortcut']}]")
    (KB / "align_report.txt").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep[:4]))


if __name__ == "__main__":
    assert sc_key("Shift+Ctrl+b") == sc_key("Ctrl+Shift+B") and sc_key('Ctrl+"') == sc_key("Ctrl+'")
    assert sc_key("Ctrl++") == "Ctrl+=" and sc_key("Alt+Shift+Ctrl++") == sc_key("Shift+Ctrl+Alt+=")
    assert SC_RE.match("Zoom In (Secondary)Ctrl++").groups() == ("Zoom In (Secondary)", "Ctrl++")
    assert SC_RE.match("Smart Guides Ctrl+U").groups() == ("Smart Guides", "Ctrl+U")
    assert SC_RE.match("Illustrator HelpF1").groups() == ("Illustrator Help", "F1")
    assert SC_RE.match("Custom View 1") is None and SC_RE.match("-180") is None
    assert exact("Shift+Ctrl++") == "Ctrl+Shift++" and exact_kys({"mods": 96, "key": 43}) == "Ctrl+Shift++"
    assert nw("abc", "abxc", lambda x, y: 2 if x == y else -2) == [(0, 0), (1, 1), (2, 3)]
    main()
