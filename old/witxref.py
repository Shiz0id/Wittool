"""Which .wit does a model use?

Character and prop textures under `tex_wi_v2/textures/` are named by an eight
hex-digit id, not by anything readable, and the model does not carry the name
either - `rep_clonetrooper/ob.war` holds bone and material names and no texture
path at all.  The engine loads them through `getTextureByHash` (0x80392CC4),
which formats `textures/%08x` (0x80702FFC) and asks the file system for it.

That id is **not** a hash of a name.  §6.13 of the roadmap already established
it for the 360 - every name in the tree was hashed both ways in eight path
forms with zero matches - and the Wii ids do not even agree with the 360 ids
for the same asset, so the two exports numbered things independently.  It is an
exporter-assigned id and nothing in the shipped data reverses it.

What does work is the other direction, and it is enough: the ids are the file
names, so scanning a model's `ob.war` for big-endian u32 values that name an
existing file tells you exactly which textures it uses.  `getTextureByHash`
rejects a negative id (0x80392CE0, `bge`), so ids are 0x00000000..0x7FFFFFFF,
which is also what every file name in the tree is.

Small ids are ambiguous: `0x00000003` is a plausible id and also a plausible
count, so a value under MIN_TRUSTED is reported separately rather than mixed in.
"""

import os
import struct
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wit as W

# Under this, a match is as likely to be an ordinary small integer as an id.
MIN_TRUSTED = 0x00010000


def texture_ids(tex_root):
    """-> {id: filename} for every hash-named .wit in a textures/ directory."""
    out = {}
    if not os.path.isdir(tex_root):
        return out
    for fn in os.listdir(tex_root):
        m = re.match(r'^([0-9a-f]{8})\.wit$', fn.lower())
        if m:
            out[int(m.group(1), 16)] = fn
    return out


def scan(blob, ids):
    """Every distinct id referenced by a blob, in the order it first appears."""
    found, seen = [], set()
    for i in range(0, max(0, len(blob) - 3)):
        v = struct.unpack_from('>I', blob, i)[0]
        if v in ids and v not in seen:
            seen.add(v)
            found.append((i, v, ids[v]))
    return found


def model_textures(ob_path, tex_root):
    ids = texture_ids(tex_root)
    with open(ob_path, 'rb') as f:
        blob = f.read()
    hits = scan(blob, ids)
    strong = [h for h in hits if h[1] >= MIN_TRUSTED]
    weak = [h for h in hits if h[1] < MIN_TRUSTED]
    return strong, weak, len(ids)


def describe(tex_root, fn):
    p = os.path.join(tex_root, fn)
    try:
        t = W.read(p)
        return '%s  %s' % ('%dx%d' % (t.width, t.height),
                           '%s%s%s' % (W.GXNAME[t.fmt],
                                       ' paired' if t.paired else '',
                                       ' cube' if t.faces == 6 else ''))
    except (ValueError, OSError) as e:
        return '(%s)' % e
