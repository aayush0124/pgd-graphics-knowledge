"""tools/ps/preset_gallery.py and presetfiles.py offline: the 2026-10-13 renderer fixes, each checked on a synthetic
job sequence that reproduced its fault, plus the .csh shape-id and .ado parsers on synthetic files. The brush and
gradient scripts the renderer generates are run in node against a small mock of the Photoshop DOM (skipped without
node); everything else is plain Python. No Photoshop, no network, no vendor file. Skipped without Pillow."""
import importlib.util, json, shutil, struct, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None
try:
    import numpy
except ImportError:  # pragma: no cover
    numpy = None
NODE = shutil.which("node")
PS = ROOT / "tools" / "ps"
sys.path.insert(0, str(PS))
import presetfiles as pf  # noqa: E402


def gallery():
    """tools/ps/preset_gallery.py under its own module name (tools/ai and tools/cdr have files of the same name)"""
    spec = importlib.util.spec_from_file_location("ps_preset_gallery", PS / "preset_gallery.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------- a mock of the Photoshop DOM for node
# Photoshop behaviour the mock encodes (seen in the 2026-10-04..07 renders): selecting a brush preset that stores tool
# options switches to that tool and loads the preset into it only; a preset that saves a colour sets the foreground;
# a useBrushSize preset keeps the tool's current diameter; a preset that stores no tool options keeps the tool's
# current ones (flow ...); a foreground change with the Mixer Brush active reloads it;
# a fill layer made in a document whose only layer is empty and transparent replaces that layer (2026-10-13).
MOCK_HEAD = r'''
var LOG = [], BR = {}, PRESETS = [], GRADS = [], NEXT = 1;
function stringIDToTypeID(s) { return s; } function charIDToTypeID(s) { return s; }
function typeIDToStringID(s) { return s; } function typeIDToCharID(s) { return s; }
var DialogModes = {NO: 3}, SaveOptions = {DONOTSAVECHANGES: 2}, NewDocumentMode = {RGB: 1}, ResampleMethod = {BICUBIC: 1},
  DocumentFill = {WHITE: 1, TRANSPARENT: 3}, PointKind = {SMOOTHPOINT: 1}, ShapeOperation = {SHAPEXOR: 1},
  ToolType = {BRUSH: "paintbrushTool", PENCIL: "pencilTool", ERASER: "eraserTool", BACKGROUNDERASER: "backgroundEraserTool"};
function UnitValue(v) { return v; } function File(p) { this.p = p; } function PathPointInfo() {} function SubPathInfo() {}
function SolidColor() { this.rgb = {red: 0, green: 0, blue: 0}; }
function hex(c) { if (!c) return null; var s = "#"; var a = [c.rgb.red, c.rgb.green, c.rgb.blue];
  for (var i = 0; i < 3; i++) { var h = Math.round(a[i]).toString(16).toUpperCase(); s += h.length < 2 ? "0" + h : h; } return s; }
function col(h) { var c = new SolidColor(); c.rgb.red = parseInt(h.substr(1, 2), 16); c.rgb.green = parseInt(h.substr(3, 2), 16); c.rgb.blue = parseInt(h.substr(5, 2), 16); return c; }
var docs = [];
var app = {currentTool: "moveTool", backgroundColor: null, documents: docs, activeDocument: null, load: null, _fg: null};
Object.defineProperty(app, "foregroundColor", {get: function () { return this._fg; },
  set: function (c) { this._fg = c; if (this.currentTool == "wetBrushTool") this.load = hex(c); }});
function Doc(name, fill) { var d = this; this.id = NEXT++; this.name = name;
  this.layers = []; this.addLayer(fill == DocumentFill.TRANSPARENT ? "Layer 1" : "Background", fill == DocumentFill.TRANSPARENT ? null : "#FFFFFF");
  this.selection = {selectAll: function () {}, deselect: function () {}, fill: function (c) { d.activeLayer.fill = hex(c); }};
  this.pathItems = {add: function () { return {select: function () {}, remove: function () {}, strokePath: function (tt) { stroke(d, tt); }}; }};
  docs.push(this); app.activeDocument = this; }
Doc.prototype.addLayer = function (name, fill) { var d = this, L = {name: name, fill: fill, remove: function () { d.layers.splice(d.layers.indexOf(L), 1); }};
  d.layers.unshift(L); d.activeLayer = L; return L; };
Doc.prototype.close = function () { docs.splice(docs.indexOf(this), 1); if (app.activeDocument === this) app.activeDocument = docs[docs.length - 1] || null; };
Doc.prototype.duplicate = function (name) { return new Doc(name, DocumentFill.WHITE); };
Doc.prototype.resizeImage = function () {};
docs.add = function (w, h, r, name, mode, fill) { return new Doc(name, fill); };
app.open = function (f) { return new Doc("opened", DocumentFill.WHITE); };
function ActionReference() {} ActionReference.prototype.putEnumerated = ActionReference.prototype.putClass =
  ActionReference.prototype.putIndex = ActionReference.prototype.putProperty = function () {};
function ActionDescriptor() { this.v = {}; }
ActionDescriptor.prototype.put = function (k, v) { this.v[k] = v; };
["putReference", "putBoolean", "putUnitDouble", "putEnumerated", "putString", "putDouble", "putInteger", "putPath", "putList"].forEach(function (m) {
  ActionDescriptor.prototype[m] = function (k, a, b) { this.v[k] = b === undefined ? a : b; }; });
ActionDescriptor.prototype.putObject = function (k, cls, o) { this.v[k] = o; };
ActionDescriptor.prototype.putClass = function (k, c) { this.v[k] = c; };
ActionDescriptor.prototype.fromStream = function () {};
ActionDescriptor.prototype.getList = function () { return {getObjectValue: function (i) { return {getObjectValue: function () {
  return {gname: GRADS[i], getString: function () { return GRADS[i]; }}; }}; }}; };
function executeAction(id, d) {
  if (id == "Strk") stroke(app.activeDocument, d.v["Usng"]);
  if (id == "Mk  ") { var D = app.activeDocument;  // like Photoshop: a fill layer replaces a document's only, empty, transparent layer
    if (D.layers.length == 1 && D.layers[0].fill === null) D.layers.pop();
    D.addLayer("gradient " + d.v["Usng"].v["Type"].v["Grad"].gname, "gradient"); } }
function stroke(d, tool) { var b = BR[tool] || {}; LOG.push({stroke: tool, preset: b.preset === undefined ? null : b.preset, diam: b.diam, flow: b.flow === undefined ? 100 : b.flow,
  fg: hex(app.foregroundColor), canvas: d.layers[d.layers.length - 1].fill, load: app.load}); }
'''
MOCK_TAIL = r'''
function selBrush(i) { var p = PRESETS[i]; if (p.tool) app.currentTool = p.tool;
  var b = BR[app.currentTool] || (BR[app.currentTool] = {preset: null, diam: 9});
  b.preset = i; if (!p.keepSize) b.diam = p.diam; if (p.fg) app.foregroundColor = col(p.fg); if (p.flow) b.flow = p.flow; }
function setDiam(px) { BR[app.currentTool].diam = px; }
function brushDiam() { return BR[app.currentTool].diam; }
function brushSig() { return ""; }
function resetTool() { var b = BR[app.currentTool]; if (b) b.flow = 100; }  // Reset Tool: options back to defaults
function optInt(k) { var b = BR[app.currentTool]; return k == "flow" && b && b.flow !== undefined ? b.flow : 100; }
function readBin() { return "xxxxxxxx"; }
function savePng(doc, p) { var a = []; for (var i = 0; i < doc.layers.length; i++) a.push(doc.layers[i].name); LOG.push({save: p, doc: doc.id, layers: a}); }
'''


def run_mock(g, body, presets=(), grads=(), start_tool="paintbrushTool"):
    """the generated script `body` in node on the mock; returns (LOG, RES)."""
    lib = (PS / "pslib.jsx").read_text(encoding="ascii")
    src = (MOCK_HEAD + "PRESETS = %s; GRADS = %s; app.currentTool = %s;\n" % (json.dumps(list(presets)), json.dumps(list(grads)),
           json.dumps(start_tool)) + lib + g.PSJ.replace("PHOTO)", '"photo.png")') + body
           + "\nconsole.log(JSON.stringify({LOG: LOG, RES: RES}));\n" + MOCK_TAIL)
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / "run.js"
        f.write_text(src, encoding="utf-8")
        r = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr[-2000:])
    out = json.loads(r.stdout.strip().splitlines()[-1])
    return out["LOG"], out["RES"]


def preset(name, cls=None, fg=None, use_size=False, d=30.0):
    """a parsed brush preset as presetfiles parse_abr's descriptor reader returns it"""
    o = {"Nm  ": name, "Brsh": {"_classID": "computedBrush", "Dmtr": {"unit": "#Pxl", "v": d}}, "useBrushSize": use_size}
    if cls:
        o["toolOptions"] = {"_classID": cls}
        if fg:
            o["toolOptions"]["FrgC"] = fg
    return o


def item(name, d):
    return {"id": f"Synthetic.abr#{name}", "name": name, "extra": {"diameter_px": d}}


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class BrushJobs(unittest.TestCase):
    """(a)/(b)/(c)/(f): every value a job needs to start clean comes from the preset file, per job."""
    def setUp(self):
        self.g = gallery()

    def jobs(self, presets):
        out = []
        for i, o in enumerate(presets):
            j = self.g.brush_job(item(o["Nm  "], o["Brsh"]["Dmtr"]["v"]), i + 1, self.g.preset_meta(o), "")
            out.append(dict(j, idx=i + 1))
        return out

    def test_tool_from_stored_tool_options(self):
        j = self.jobs([preset("Blend", "SmTl"), preset("Oils", "MixB"), preset("Edge", "ErTl"), preset("Plain")])
        self.assertEqual([x["tool"] for x in j], ["smudgeTool", "wetBrushTool", "eraserTool", "paintbrushTool"])
        with self.assertRaises(ValueError):
            self.g.preset_meta(preset("Odd", "XxTl"))

    def test_saved_colours_decoded_and_light_ones_get_a_dark_canvas(self):
        aurora = {"_classID": "HSBC", "H   ": {"unit": "#Ang", "v": 184.9383544921875}, "Strt": 51.76, "Brgh": 64.31}
        j = self.jobs([preset("DP Cloud", "PbTl", {"_classID": "RGBC", "Rd  ": 255.0, "Grn ": 255.0, "Bl  ": 255.0}),
                       preset("Aurora", "PbTl", aurora), preset("Plain")])
        self.assertEqual([x["fg"] for x in j], ["#FFFFFF", "#4F9DA4", None])  # #4F9DA4: what Aurora painted, measured
        self.assertEqual([x["dark"] for x in j], [True, False, False])

    def test_diameter_is_the_stored_one_even_for_use_brush_size(self):
        j = self.jobs([preset("Rough Round Bristle", d=104.0), preset("Round Point Thin Bristle", use_size=True, d=13.0)])
        self.assertEqual([x["d"] for x in j], [104.0, 13.0])

    def test_how_names_tool_size_and_canvas(self):
        j = self.jobs([preset("DP Cloud", "PbTl", {"_classID": "RGBC", "Rd  ": 255.0, "Grn ": 255.0, "Bl  ": 255.0}),
                       preset("Edge", "ErTl", d=40.0)])
        how, mode = self.g.brush_how(j[0], "ok|paintbrushTool|dark")
        self.assertIsNone(mode)
        self.assertIn("(#FFFFFF) on a black canvas", how)
        self.assertIn("stored 30 px", how)
        self.assertIn("tool checked", how)  # resume marker do_panel looks for
        how, _ = self.g.brush_how(j[1], "ok|eraserTool")
        self.assertIn("eraserTool", how)
        self.assertIn("black canvas", how)
        how, mode = self.g.brush_how(j[1], "ok|smudgeTool|photo4")
        self.assertEqual(mode, "4")
        self.assertIn("saturated colour bands", how)


@unittest.skipIf(Image is None or NODE is None, "needs Pillow and node (the generated script runs on a DOM mock)")
class BrushScriptSequences(unittest.TestCase):
    """the generated js_brushes loop run on synthetic job sequences that reproduced each fault"""
    def setUp(self):
        self.g = gallery()

    def run_seq(self, presets):
        """presets: [(parsed preset, mock behaviour {tool, fg, keepSize, diam})] -> strokes, RES"""
        jobs = []
        for i, (o, _) in enumerate(presets):
            jobs.append(dict(self.g.brush_job(item(o["Nm  "], o["Brsh"]["Dmtr"]["v"]), i, self.g.preset_meta(o), ""),
                             idx=i, out=f"r{i}.png"))
        log, res = run_mock(self.g, self.g.js_brushes(jobs), [b for _, b in presets])
        self.assertTrue(all(str(v).startswith("ok") for v in res.values()), res)
        return [x for x in log if "stroke" in x]

    def test_a_f_saved_colour_never_reaches_the_next_preset(self):
        s = self.run_seq([(preset("DP Cloud", "PbTl", {"_classID": "RGBC", "Rd  ": 255.0, "Grn ": 255.0, "Bl  ": 255.0}),
                           {"tool": "paintbrushTool", "fg": "#FFFFFF", "diam": 30}),
                          (preset("DP Earl", "PbTl"), {"tool": "paintbrushTool", "diam": 30}),
                          (preset("Plain"), {"diam": 30})])
        self.assertEqual([(x["fg"], x["canvas"]) for x in s],
                         [("#FFFFFF", "#000000"), ("#000000", "#FFFFFF"), ("#000000", "#FFFFFF")])

    def test_a_mixer_load_is_reset_after_a_white_preset(self):
        s = self.run_seq([(preset("DP Cloud", "PbTl", {"_classID": "RGBC", "Rd  ": 255.0, "Grn ": 255.0, "Bl  ": 255.0}),
                           {"tool": "paintbrushTool", "fg": "#FFFFFF", "diam": 30}),
                          (preset("Oil Pastel-Hard Opaque", "MixB"), {"tool": "wetBrushTool", "diam": 30})])
        self.assertEqual(s[1]["stroke"], "wetBrushTool")
        self.assertEqual(s[1]["load"], "#000000")

    def test_b_use_brush_size_preset_paints_at_its_own_size(self):
        s = self.run_seq([(preset("Rough Round Bristle", d=104.0), {"diam": 104}),
                          (preset("Round Point Thin Bristle", use_size=True, d=13.0), {"diam": 13, "keepSize": True})])
        self.assertEqual([x["diam"] for x in s], [104, 13])

    def test_g_tool_options_of_one_preset_never_reach_the_next(self):
        s = self.run_seq([(preset("DP Stubble", "PbTl"), {"tool": "paintbrushTool", "diam": 30, "flow": 18}),
                          (preset("Hard Round", use_size=True), {"diam": 30, "keepSize": True})])
        self.assertEqual([x["flow"] for x in s], [18, 100])

    def test_c_smudge_mixer_eraser_stroke_their_own_preset(self):
        s = self.run_seq([(preset("Inkbox"), {"diam": 30}),
                          (preset("Impressionist Blender", "SmTl"), {"tool": "smudgeTool", "diam": 30}),
                          (preset("Real Oils", "MixB"), {"tool": "wetBrushTool", "diam": 30}),
                          (preset("Natural Edge", "ErTl"), {"tool": "eraserTool", "diam": 30})])
        self.assertEqual([(x["stroke"], x["preset"]) for x in s],
                         [("paintbrushTool", 0), ("smudgeTool", 1), ("wetBrushTool", 2), ("eraserTool", 3)])
        self.assertEqual(s[3]["canvas"], "#000000")  # the eraser paints white on black

    def test_c_tool_mismatch_fails_the_job_instead_of_stroking_a_stale_brush(self):
        jobs = [dict(self.g.brush_job(item("Blend", 30.0), 0, self.g.preset_meta(preset("Blend", "SmTl")), ""), idx=0, out="r0.png")]
        log, res = run_mock(self.g, self.g.js_brushes(jobs), [{"tool": "paintbrushTool", "diam": 30}])  # app ignores it
        self.assertIn("not its own smudgeTool", list(res.values())[0])
        self.assertFalse([x for x in log if "stroke" in x])


@unittest.skipIf(Image is None or NODE is None, "needs Pillow and node (the generated script runs on a DOM mock)")
class GradientScript(unittest.TestCase):
    def test_d_every_gradient_renders_alone_in_its_own_document(self):
        g = gallery()
        names = ["Neutral Density", "Neutral Density 10", "Foreground to Transparent"]
        jobs = [{"k": f"k{i}", "out": f"w{i}.png", "out2": f"b{i}.png", "i": i, "zname": n} for i, n in enumerate(names)]
        log, res = run_mock(g, g.js_gradients("x.grd", jobs), grads=names)
        self.assertEqual(set(res.values()), {"ok"})
        saves = [x for x in log if "save" in x]
        self.assertEqual(len(saves), 6)
        for i, n in enumerate(names):
            for s in saves[2 * i:2 * i + 2]:
                self.assertEqual(s["layers"], ["gradient " + n, "Background"])
        self.assertEqual(len({s["doc"] for s in saves}), 3)


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class Patterns(unittest.TestCase):
    def setUp(self):
        self.g = gallery()

    def test_e_render_square_is_the_thumbnail_box(self):
        for w in (16, 128, 300, 1024):
            it = {"id": f"P.pat#{w}", "name": str(w), "extra": {"pattern_id": "id", "width": w, "height": w}}
            j = self.g.pattern_job(it)
            self.assertEqual(j["s"], 300)
            self.assertEqual("1:1 crop" in self.g.pattern_how(j), w > 300)

    @unittest.skipIf(numpy is None, "numpy not installed (thumb_wb needs it)")
    def test_e_thumbnail_keeps_pixels_1_to_1_and_the_frame_size(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            im = Image.new("RGB", (300, 300))
            im.putdata([(0, 0, 0) if (x + y) % 2 else (255, 255, 255) for y in range(300) for x in range(300)])  # 1 px grain
            im.save(t / "w.png")
            im.save(t / "b.png")
            self.g.thumb_wb(t / "w.png", t / "b.png", t / "o.png")
            o = Image.open(t / "o.png").convert("RGB")
            self.assertEqual(o.size, (320, 320))
            self.assertEqual([o.getpixel((10 + x, 10 + y)) for x, y in ((0, 0), (1, 0), (151, 77))],
                             [im.getpixel((x, y)) for x, y in ((0, 0), (1, 0), (151, 77))])


@unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
class RerenderBookkeeping(unittest.TestCase):
    def test_ids_reads_rerender_all_and_keep_old_moves_frames_once(self):
        g = gallery()
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            g.OUT, g.RAW = t / "gal", t / "raw"
            g.OUT.mkdir(), g.RAW.mkdir()
            (t / "all.json").write_text(json.dumps({"ps_preset": ["A.abr#x"], "ai_effect": ["y"]}), encoding="utf-8")
            self.assertEqual(g.read_ids(t / "all.json"), ["A.abr#x"])
            (t / "ids.txt").write_text("A.abr#x\nB.grd#y\n", encoding="utf-8")
            self.assertEqual(g.read_ids(t / "ids.txt"), ["A.abr#x", "B.grd#y"])
            k = g.key("A.abr#x")
            st = types_state(g, {k: {"key": k, "id": "A.abr#x", "how": "old"}}, {"B.grd#y": "ERR"})
            (g.OUT / f"{k}.png").write_bytes(b"old")
            (g.RAW / f"{k}.png").write_bytes(b"stale raw")
            g.keep_old(st, ["A.abr#x", "B.grd#y"], pre=t / "pre")
            self.assertEqual((t / "pre" / f"{k}.png").read_bytes(), b"old")
            self.assertFalse((g.RAW / f"{k}.png").exists())
            self.assertEqual((st.index, st.failed), ({}, {}))
            (g.OUT / f"{k}.png").write_bytes(b"new")  # a second pass never overwrites the frame kept first
            g.keep_old(st, ["A.abr#x"], pre=t / "pre")
            self.assertEqual((t / "pre" / f"{k}.png").read_bytes(), b"old")
            g.ONLY = {"A.abr#x"}
            self.assertTrue(st.done({"id": "C.pat#z"}))   # outside the list: never rendered by an --ids run
            self.assertFalse(st.done({"id": "A.abr#x"}))


def types_state(g, index, failed):
    st = g.State.__new__(g.State)
    st.index, st.failed, st.notr, st.fresh = dict(index), dict(failed), {}, set()
    return st


# ---------------------------------------------------------------- parsers
def ustr(s):
    return struct.pack(">I", len(s) + 1) + (s + "\x00").encode("utf-16-be")


def csh(shapes):
    """a minimal 'cush' file: [(name, uuid, (top, left, bottom, right))]"""
    b = b"cush" + struct.pack(">II", 2, len(shapes))
    for name, uid, bounds in shapes:
        b += ustr(name)
        b += b"\x00" * (-len(b) % 4)
        body = b"$" + uid.encode("ascii") + struct.pack(">4i", *bounds) + b"\x00" * 16
        b += struct.pack(">II", 1, len(body)) + body
        b += b"\x00" * (-len(b) % 4)
    return b


class Parsers(unittest.TestCase):
    def test_csh_shape_id_is_the_37_bytes_even_when_the_top_bound_is_negative(self):
        uid = "273c5899-d071-11d5-b052-dfd8889e7d2b"
        ents, _ = pf.parse_csh(csh([("Arrow 5", uid, (-3, 0, 90, 120)), ("Tiger", uid.replace("2", "7"), (0, 0, 9, 9))]))
        self.assertEqual([e["shape_id"] for e in ents], ["$" + uid, "$" + uid.replace("2", "7")])

    @unittest.skipIf(Image is None, "Pillow not installed (the gallery renderer needs it)")
    def test_csh_ids_agree_with_the_renderers_bounds_reader(self):
        uid = "dc737b5e-d070-11d5-b052-dfd8889e7d2b"
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "s.csh"
            p.write_bytes(csh([("Light Bulb 2", uid, (-1, -2, 50, 60))]))
            sid, top, left, bottom, right, _ = gallery().csh_bounds(p)[0]
            self.assertEqual(("$" + sid, top, left, bottom, right), (pf.parse_csh(p.read_bytes())[0][0]["shape_id"], -1, -2, 50, 60))

    def test_ado_duotone_inks_names_and_curves(self):
        b = bytearray(524)
        struct.pack_into(">HH", b, 0, 1, 2)
        struct.pack_into(">H4H", b, 4, 2, 65535, 65535, 65535, 0)          # CMYK 0/0/0/100 (0xFFFF = 0 %)
        b[14:24] = struct.pack(">H", 3) + b"424C\x00\x00\x00\x00"           # a Pantone ink by its code
        for i, nm in enumerate((b"Black", b"PANTONE 424 CVC")):
            b[0x2c + 64 * i] = len(nm)
            b[0x2d + 64 * i:0x2d + 64 * i + len(nm)] = nm
        for i, pts in enumerate(({0: 0, 70: 150, 100: 980}, {0: 5, 5: 50, 100: 980})):
            v = [pts.get(t, 0xFFFF) for t in pf.ADO_TONES] + [0]
            struct.pack_into(">14H", b, 0x12c + 28 * i, *v)
        ents, meta = pf.parse_ado(bytes(b))
        self.assertEqual(ents, [])
        self.assertEqual(meta["inks"], [{"name": "Black", "space": "CMYK", "value": [0.0, 0.0, 0.0, 100.0]},
                                        {"name": "PANTONE 424 CVC", "space": "Pantone", "value": "424C"}])
        self.assertEqual(meta["curves"], [{0: 0.0, 70: 15.0, 100: 98.0}, {0: 0.5, 5: 5.0, 100: 98.0}])
        self.assertIs(pf.PARSERS[".ado"], pf.parse_ado)
        with self.assertRaises(ValueError):
            pf.parse_ado(bytes(100))


if __name__ == "__main__":
    unittest.main()
