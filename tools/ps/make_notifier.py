"""Build tools/ps/notifier.jsx: an 'All ' event notifier that appends {event, desc} lines to work/ps/notify.log."""
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides
HERE = Path(__file__).parent
LOG = (PGD / "work/ps/notify.log").as_posix()
body = (HERE / "pslib.jsx").read_text(encoding="ascii") + r"""
try {
  var _d = arguments[0], _e = arguments[1], _s = tid2s(_e), _o = "{}";
  try { _o = J(d2o(_d)); } catch (e1) { _o = J({err: String(e1)}); }
  var _f = new File("%s"); _f.encoding = "UTF-8"; _f.open("a");
  _f.writeln('{"event":' + J(_s) + ',"desc":' + _o + '}'); _f.close();
} catch (e) {}
""" % LOG
(HERE / "notifier.jsx").write_text(body, encoding="ascii")
