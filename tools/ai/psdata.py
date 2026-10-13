"""PGD / Illustrator: decode the parameter block Illustrator stores for a Photoshop effect (live effect
'PSAdapter_plugin_<code>' / 'Adobe PSL ...'): the dictionary's /Binary (data) entry, ASCII85 in the .ai file.

Layout read from the files (no documentation used): uint32 1, then entries of key(4) flags(4) type(4) value, where
flags 0x2000 marks an enumerated value (type = enum type id, value = 4-char enumerator), type 'long' = int32,
'doub' = float64, 'bool' = 1 byte. Anything else stops the decode and the rest is returned as hex.
"""
import base64, struct


def a85(value_raw):
    body = "".join(l[1:] if l.startswith("%") else l for l in value_raw.split("\n")[1:])
    return base64.a85decode(body.split("~>")[0])


def decode(b):
    out, i = [], 4
    if len(b) < 4 or struct.unpack(">I", b[:4])[0] != 1:
        return out, b.hex()
    while i + 12 <= len(b):
        key, flags, ty = b[i:i + 4].decode("latin-1"), struct.unpack(">I", b[i + 4:i + 8])[0], b[i + 8:i + 12].decode("latin-1")
        i += 12
        if flags & 0x2000:
            out.append({"key": key, "ps_type": "enum", "enum_type": ty, "value": b[i:i + 4].decode("latin-1")})
            i += 4
        elif ty == "long":
            out.append({"key": key, "ps_type": ty, "value": struct.unpack(">i", b[i:i + 4])[0]})
            i += 4
        elif ty == "doub":
            out.append({"key": key, "ps_type": ty, "value": struct.unpack(">d", b[i:i + 8])[0]})
            i += 8
        elif ty == "bool":
            out.append({"key": key, "ps_type": ty, "value": bool(b[i])})
            i += 1
        elif flags & 0x80000000:  # nested descriptor (a colour 'RGBC', a point 'Pnt '): key + class kept, no value
            out.append({"key": key, "ps_type": "object", "class": ty})
            return out, b[i - 12:].hex()
        else:
            return out, b[i - 12:].hex()
    return out, b[i:].hex()


if __name__ == "__main__":
    b = bytes.fromhex("000000014745666b000020004745667453746d704c674472000000006c6f6e6700000019536d7468000000006c6f6e6700000005")
    d, rest = decode(b)
    assert [x["key"] for x in d] == ["GEfk", "LgDr", "Smth"] and d[1]["value"] == 25 and rest == "", (d, rest)
    print("ok", d)
