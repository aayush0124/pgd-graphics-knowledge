// PGD Photoshop helpers, prepended to every psdrv.js() call. Pure ASCII, ES3.
var S2T = function (s) { return stringIDToTypeID(s); };
var C2T = function (c) { return charIDToTypeID(c); };
function tid2s(t) {  // typeID -> stringID, else 4-char id in quotes
  var s = ""; try { s = typeIDToStringID(t); } catch (e) {}
  if (s) return s;
  try { s = typeIDToCharID(t); } catch (e2) {}
  return s ? "'" + s + "'" : String(t);
}
function J(v) {  // minimal JSON.stringify
  if (v === null || v === undefined) return "null";
  var t = typeof v;
  if (t == "number") return isFinite(v) ? String(v) : "null";
  if (t == "boolean") return v ? "true" : "false";
  if (t == "string") return '"' + v.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\r/g, "\\r").replace(/\n/g, "\\n").replace(/\t/g, "\\t").replace(/[\x00-\x1f]/g, " ") + '"';
  if (v instanceof Array) { var a = []; for (var i = 0; i < v.length; i++) a.push(J(v[i])); return "[" + a.join(",") + "]"; }
  var o = []; for (var k in v) if (v.hasOwnProperty(k)) o.push(J(String(k)) + ":" + J(v[k])); return "{" + o.join(",") + "}";
}
var DVT = {};
function _dvt() {
  var m = ["ALIASTYPE", "BOOLEANTYPE", "CLASSTYPE", "DOUBLETYPE", "ENUMERATEDTYPE", "INTEGERTYPE", "LARGEINTEGERTYPE",
           "LISTTYPE", "OBJECTTYPE", "RAWTYPE", "REFERENCETYPE", "STRINGTYPE", "UNITDOUBLE"];
  for (var i = 0; i < m.length; i++) try { DVT[String(DescValueType[m[i]])] = m[i]; } catch (e) {}
}
_dvt();
// value at key/index of a descriptor or list -> {t:type, v:value, ...}
function dval(d, k, depth) {
  var ty = DVT[String(d.getType(k))] || String(d.getType(k)), r = {t: ty};
  try {
    switch (ty) {
      case "BOOLEANTYPE": r.v = d.getBoolean(k); break;
      case "DOUBLETYPE": r.v = d.getDouble(k); break;
      case "INTEGERTYPE": r.v = d.getInteger(k); break;
      case "LARGEINTEGERTYPE": r.v = d.getLargeInteger(k); break;
      case "STRINGTYPE": r.v = d.getString(k); break;
      case "UNITDOUBLE": r.v = d.getUnitDoubleValue(k); r.unit = tid2s(d.getUnitDoubleType(k)); break;
      case "ENUMERATEDTYPE": r.etype = tid2s(d.getEnumerationType(k)); r.v = tid2s(d.getEnumerationValue(k)); break;
      case "CLASSTYPE": r.v = tid2s(d.getClass(k)); break;
      case "OBJECTTYPE": r.cls = tid2s(d.getObjectType(k)); r.v = depth > 8 ? "..." : d2o(d.getObjectValue(k), depth + 1); break;
      case "LISTTYPE": r.v = depth > 8 ? "..." : l2o(d.getList(k), depth + 1); break;
      case "ALIASTYPE": r.v = String(d.getPath(k)); break;
      case "RAWTYPE": r.v = "<raw " + d.getData(k).length + " bytes>"; break;
      case "REFERENCETYPE": r.v = "<reference>"; break;
    }
  } catch (e) { r.err = String(e); }
  return r;
}
function d2o(d, depth) {  // ActionDescriptor -> {key: dval}
  var o = {}; depth = depth || 0;
  for (var i = 0; i < d.count; i++) { var k = d.getKey(i); o[tid2s(k)] = dval(d, k, depth); }
  return o;
}
function l2o(l, depth) {
  var a = [], n = Math.min(l.count, 400);
  for (var i = 0; i < n; i++) a.push(dval(l, i, depth));
  if (l.count > n) a.push({t: "TRUNCATED", v: l.count});
  return a;
}
function newDoc(name, w, h) {  // our own scratch document (RGB, 8 bit, white)
  var d = app.documents.add(UnitValue(w || 640, "px"), UnitValue(h || 360, "px"), 72, name, NewDocumentMode.RGB, DocumentFill.WHITE);
  return d;
}
function openTest(path) { return app.open(new File(decodeURIComponent(path))); }
function closeNoSave(name) {
  for (var i = app.documents.length - 1; i >= 0; i--) if (app.documents[i].name == name) app.documents[i].close(SaveOptions.DONOTSAVECHANGES);
}
function activate(name) { for (var i = 0; i < app.documents.length; i++) if (app.documents[i].name == name) { app.activeDocument = app.documents[i]; return true; } return false; }
function layerDesc() {
  var r = new ActionReference(); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt"));
  return executeActionGet(r);
}
