"""PGD/CDR: the interactive vector effects as cdr_effect items, with params read from the VGCore 25.1 typelib.

Effects-menu dockers (Blend, Contour, Envelope, Extrude, Lens, Bevel ...) are enriched in place by enrich();
effects that live in the toolbox / Object menu (Drop Shadow, Inner Shadow, Block Shadow, Distort, Perspective,
Transparency, PowerClip) and each Lens type become their own items in vector_items().
"""
import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[2] / "work" / "cdr"
STRINGS = Path(r"C:/Program Files/Corel/CorelDRAW Graphics Suite/25/Languages/EN/Data/strings.xml")
_T = None

# display name -> (typelib interface, member) for each effect's object-model apply call
DOCKER_API = {
    "Blend": [("IVGShape", "CreateBlend")],
    "Contour": [("IVGShape", "CreateContour")],
    "Envelope": [("IVGShape", "CreateEnvelope"), ("IVGShape", "CreateEnvelopeFromShape"),
                 ("IVGShape", "CreateEnvelopeFromCurve")],
    "Extrude": [("IVGShape", "CreateExtrude"), ("IVGEffectExtrude", "SetBevel")],
    "Lens": [("IVGShape", "CreateLens")],
}
# tool items found in DrawUI.xml (toolbox groupedRadioButtons bound to AppOrViewDataSource.ActiveTool), captions live
TOOLS = {"Blend": "d72c98e8-59be-4a31-b9db-1d0e83bdd218", "Contour": "441d6b88-877e-4d00-951f-4521b9987650",
         "Distort": "f42edc69-976b-4917-802a-1c4fed6297ef", "Envelope": "1f16cb33-9819-4fa7-a3cd-5c4d61ba2db2",
         "Extrude": "c5555cfc-1c54-4c5b-ad28-60a4ec569798", "Block Shadow": "249b7791-6d54-401b-a326-378c53773a52",
         "Transparency": "b4b2ecec-4dc4-4c76-aa55-abcb1c862cde", "Shadow": "e65d1597-722d-4afb-82fe-964d7ddff531",
         "Drop Shadow tool": "e8ef757d-f13c-109b-4a8d-bca6c3e4e9c9",
         "Inner Shadow Tool": "08f5977a-dd28-b8b1-4fe0-767c7eb7147e"}
DISTORT = [("PushPull", "CreatePushPullDistortion", "Push & Pull", "5cc921c9-24af-49b5-a097-ab131a45a2eb"),
           ("Zipper", "CreateZipperDistortion", "Zipper", "de74addf-6714-43d4-a026-568871e4498f"),
           ("Twister", "CreateTwisterDistortion", "Twister", "7e6c8fad-acf5-4529-b095-397d7f02dacf")]
# transparency type radios (TransparencyStyleDS FillTypeStr), captions read live; pattern -> cdrPatternFillType value
TRANSP = [("Uniform", "ApplyUniformTransparency", "Uniform Transparency", "311d886a-7b2c-668a-4f15-f31083aa0298", None),
          ("Fountain", "ApplyFountainTransparency", "Fountain Transparency", "40815553-8129-d491-4d0b-cd7570bdb7bd",
           None),
          ("FullColor", "ApplyPatternTransparency", "Vector Pattern Transparency",
           "b70d6f3d-4336-82b4-4f96-e33e8b20e475", 1),
          ("Bitmap", "ApplyPatternTransparency", "Bitmap Pattern Transparency",
           "ede98884-e12a-198a-4d89-29a809d102e4", 2),
          ("TwoColor", "ApplyPatternTransparency", "Two-color Pattern Transparency",
           "79a009ac-52b5-7e91-4a33-a50ea1fb2a63", 0),
          ("Texture", "ApplyTextureTransparency", "Texture Transparency", "ab90096d-03f7-dc97-4bb4-73ca4e0b3baf",
           None)]
# cdrLensType value -> strings.xml guid of the Lens docker caption (looked up by text in strings.xml, checked live)
LENS = [("cdrLensMagnify", "Magnify"), ("cdrLensFishEye", "Fish Eye"), ("cdrLensWireframe", "Wireframe"),
        ("cdrLensColorLimit", "Color Limit"), ("cdrLensColorAdd", "Color Add"), ("cdrLensInvert", "Invert"),
        ("cdrLensBrighten", "Brighten"), ("cdrLensTintedGrayscale", "Tinted Grayscale"),
        ("cdrLensHeatMap", "Heat Map"), ("cdrLensTransparency", "Transparency"),
        ("cdrLensCustomColorMap", "Custom Color Map")]


def tlb():
    global _T
    if _T is None:
        L = json.loads((WORK / "tlb" / "VGCoreAuto.json").read_text(encoding="utf-8"))
        _T = {t["name"]: t for t in L["types"]}
    return _T


def member(iface, name):
    return next(m for m in tlb()[iface]["members"] if m["name"] == name and m["invkind"] == "func")


def sig(iface, name):
    m = member(iface, name)
    a = ", ".join(x["name"] + ": " + x["type"] + (f" = {x['default']!r}" if "default" in x else
                                                  (" (optional)" if x.get("optional") else "")) for x in m["args"])
    return f"{iface[3:] if iface.startswith('IVG') else iface}.{name}({a}) -> {m['returns']}"


def params(iface, name, skip=()):
    out = []
    for a in member(iface, name)["args"]:
        if a["name"] in skip:
            continue
        t = a["type"]
        p = {"name": a["name"], "key": a["name"]}
        en = tlb().get(t)
        if en and en["kind"] == "enum":
            p["type"] = "enum"
            p["enum"] = [{"value": v["value"], "label": v["name"]} for v in en["values"]]
        elif t in ("double", "single"):
            p["type"] = "number"
        elif t in ("long", "int", "short"):
            p["type"] = "int"
        elif t == "bool":
            p["type"] = "bool"
        elif t == "string":
            p["type"] = "string"
        elif t == "IVGColor*":
            p["type"] = "color"
        elif t.endswith("*") and t.startswith("IVG"):
            p["type"] = "object"
        else:
            p["type"] = "unknown"
        if "default" in a and not (p["type"] in ("color", "object") and a["default"] in (0, None)):
            d = a["default"]
            p["default"] = bool(d) if p["type"] == "bool" else d
        x = {"com_type": t}
        if "default" not in a and not a.get("optional"):
            x["required"] = True
        if p["type"] in ("color", "object") and "default" in a:
            x["default"] = "Nothing (VT_DISPATCH default 0: pass None from Python)"
        p["extra"] = x
        out.append(p)
    return out


def menu_guid(path):
    """Full GUID of a live menu entry (menu_walk.py output); never typed by hand."""
    rows = json.loads((WORK / "menu_live.json").read_text(encoding="utf-8"))
    return next(r["guid"] for r in rows if r["path"] == path)


def string_guid(text):
    import xml.etree.ElementTree as ET
    for e in ET.parse(STRINGS).getroot():
        if e.text == text:
            return e.get("guid")
    return None


BEVEL = ("custom effect read back through Effect.Custom (BevelToolOM.tlb IEffectBevel: Type cdrBevelType "
         "{0 cdrBevelSoftEdge, 1 cdrBevelEmboss}, Mode cdrBevelMode {0 cdrBevelCenter, 1 cdrBevelOffset}, Offset, "
         "LightColor, LightIntensity, LightDirection, LightAltitude, ShadowColor, AmbientIntensity)")


def enrich(items, tests):
    for it in items:
        if it["name"] == "Bevel" and it.get("extra", {}).get("opens_docker"):
            it["extra"]["object_model"] = BEVEL
            it["error"] = ("creation call not established: VGCoreAuto.tlb has no CreateBevel; Shape.CreateCustomEffect"
                           "(EffectID, Parameters) needs the bevel EffectID, not probed")
            continue
        api = DOCKER_API.get(it["name"]) if it.get("extra", {}).get("opens_docker") else None
        if not api:
            continue
        iface, mem = api[0]
        it["invoke"]["cdr_com"] = " | ".join(sig(i, m) for i, m in api)
        it["params"] = params(iface, mem)
        it["category"] = "Vector"
        it["requires"] = "vector object(s) (Blend: two shapes)" if it["name"] == "Blend" else "vector object"
        if it["name"] in TOOLS:
            it["extra"]["tool_guid"] = TOOLS[it["name"]]
        t = tests.get("vector:" + it["name"])
        it["evidence"] += "; apply call + params + defaults from typelib VGCoreAuto.tlb 25.1"
        if t:
            it["evidence"] += "; apply test: " + t.get("result", "")
            if t.get("error"):
                it["error"] = t["error"]


def vector_items(caps, tests):
    def item(name, iid, path, apis, req, guid=None, skip=(), extra=None):
        iface, mem = apis[0]
        it = {"name": name, "id": iid, "path": path, "category": "Vector",
              "invoke": {"cdr_com": " | ".join(sig(i, m) for i, m in apis)},
              "params": params(iface, mem, skip), "requires": req,
              "evidence": "apply call + params + defaults from typelib VGCoreAuto.tlb 25.1"}
        if guid:
            it["invoke"]["cdr_guid"] = guid
        if extra:
            it["extra"] = extra
        t = tests.get(iid)
        if t:
            it["evidence"] += "; apply test: " + t.get("result", "")
            if t.get("error"):
                it["error"] = t["error"]
        return it

    # display names: live GetCaptionText of the tool / property-bar radio (DISTORT, TRANSP) or strings.xml (SHADOW)
    out = [
        item("Drop Shadow", "vector:DropShadow", "Toolbox/Shadow/Drop Shadow tool", [("IVGShape", "CreateDropShadow")],
             "vector or bitmap object", TOOLS["Drop Shadow tool"],
             extra={"caption_string_guid": string_guid("Drop Shadow")}),
        item("Inner Shadow", "vector:InnerShadow", "Toolbox/Shadow/Inner Shadow Tool",
             [("IVGShape", "CreateInnerShadow")], "closed vector object", TOOLS["Inner Shadow Tool"],
             extra={"caption_string_guid": string_guid("Inner Shadow")}),
    ]
    for code, api, label, radio in DISTORT:
        out.append(item(label, "vector:Distort:" + code, "Toolbox/Distort/" + label, [("IVGShape", api)],
                        "vector object", TOOLS["Distort"],
                        extra={"mode_radio_guid": radio, "property_bar": "WDistortionDataSource.ActiveDistortionType"}))
    out.append(item("Add Perspective", "vector:Perspective", "Object/Perspective/Add Perspective",
                    [("IVGShape", "CreatePerspective")], "vector object or group",
                    menu_guid("Object/Perspective/Add Perspective")))
    for code, api, label, radio, pat in TRANSP:
        it = item(label, "vector:Transparency:" + code, "Toolbox/Transparency/" + label, [("IVGTransparency", api)],
                  "any object (Shape.Transparency)", TOOLS["Transparency"],
                  skip=("Type",) if pat is not None else (), extra={"type_radio_guid": radio})
        if pat is not None:
            it["invoke"]["cdr_com"] = f"Shape.Transparency.{api}(Type={pat}, ...) | " + it["invoke"]["cdr_com"]
            it["extra"]["pattern_type"] = pat
        out.append(it)
    out.append(item("PowerClip", "vector:PowerClip", "Object/PowerClip/Place Inside Frame",
                    [("IVGShape", "AddToPowerClip")], "content shape + container shape",
                    menu_guid("Object/PowerClip/Place Inside Frame"),
                    extra={"caption_string_guid": string_guid("PowerClip")}))
    # Block Shadow: tool exists, no object-model call in VGCoreAuto.tlb 25.1
    out.append({"name": "Block Shadow", "id": "vector:BlockShadow", "path": "Toolbox/Block Shadow",
                "category": "Vector", "invoke": {"cdr_guid": TOOLS["Block Shadow"]}, "requires": "vector object",
                "evidence": "tool item in DrawUI.xml toolbox, caption read live",
                "error": "no Block Shadow member in VGCoreAuto.tlb 25.1 (searched every interface): script can "
                         "only select the tool (Automation.InvokeItem), parameters not probed"})
    # Bevel: custom effect (BevelToolOM.tlb IEffectBevel), docker in the Effects menu
    for code, label in LENS:
        en = next(v["value"] for v in tlb()["cdrLensType"]["values"] if v["name"] == code)
        it = item(label, "lens:" + code, "Effects/Lens/" + label, [("IVGShape", "CreateLens")], "closed vector object",
                  menu_guid("Effects/Lens"), skip=("Type",),
                  extra={"lens_type": en, "caption_string_guid": string_guid(label)})
        it["category"] = "Lens"
        it["invoke"]["cdr_com"] = f"Shape.CreateLens(Type={en} ({code}), ...) | " + sig("IVGShape", "CreateLens")
        it["evidence"] += "; type caption from strings.xml (Languages/EN)"
        out.append(it)
    return out
