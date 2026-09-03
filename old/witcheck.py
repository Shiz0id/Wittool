"""What the shipped engine will and will not accept in a .wit.

Every rule here is either a branch in main.dol or a property the shipped
converter never violates in 10,317 files.  They are separated on purpose: a
REFUSE is the engine rejecting or silently replacing your texture, a WARN is
you leaving the envelope the game's own art stays inside.

The one that costs people an afternoon is MAX_DIMENSION.  Go over it and the
loader does not complain, it quietly loads misctex/generic/fill instead - a
16x16 flat white - so the surface renders blank and nothing is logged.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wit as W

# 0x803EE288 / 0x803EE294: `cmplwi 1024 / bgt`, and the branch loads
# "misctex/generic/fill" (0x8070300C) through getTextureByName instead.
MAX_DIMENSION = 1024

# 0x80392CC4: the texture record table is `li r0, 1536` entries of 76 bytes.
MAX_RESIDENT = 1536

REFUSE, WARN, NOTE = 'REFUSE', 'WARN', 'NOTE'


def _pot(v):
    return v > 0 and (v & (v - 1)) == 0


def check_dims(width, height, fmt, levels, faces=1):
    """-> [(severity, message)], worst first. Empty means the engine is happy."""
    out = []

    if width < 1 or height < 1:
        out.append((REFUSE, 'width and height must both be at least 1'))
        return out

    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        out.append((REFUSE,
                    '%dx%d is over the %d limit - the loader does not fail, it '
                    'silently substitutes misctex/generic/fill (16x16 flat white) '
                    'at 0x803EE29C, so the surface renders blank with nothing logged'
                    % (width, height, MAX_DIMENSION)))

    if levels < 1:
        out.append((REFUSE, 'a texture needs at least one level'))
    if levels > W.max_levels(width, height):
        out.append((REFUSE, '%d levels is more than %dx%d can produce (%d)'
                    % (levels, width, height, W.max_levels(width, height))))

    if faces not in (1, 6):
        out.append((REFUSE, 'faces must be 1, or 6 for a cube map'))
    if faces == 6 and width != height:
        out.append((WARN, 'a cube map with non-square faces (%dx%d); every shipped '
                    'cube map is square' % (width, height)))

    npot = not (_pot(width) and _pot(height))
    if npot and levels > 1:
        out.append((REFUSE,
                    '%dx%d is not a power of two and carries %d levels. Halving '
                    'stops being exact, so the level the engine addresses and the '
                    'level you wrote drift apart. All 19 non-power-of-two textures '
                    'in the shipped tree are single-level.' % (width, height, levels)))

    if fmt == W.CMPR:
        # A CMPR level is stored as ceil(w/4) x ceil(h/4) blocks and stops there,
        # but the texture unit addresses it as whole 8x8 tiles.  Those agree only
        # while the block grid is even, or the level is smaller than a tile in
        # that direction.  The converter dodges this by exporting such sizes as
        # RGBA8 - every awkward size in the tree (18x17, 33x16, 56x56, 400x200)
        # is RGBA8, never CMPR.
        for lv in range(levels):
            lw, lh = W.level_dims(width, height, lv)
            bw, bh = (lw + 3) // 4, (lh + 3) // 4
            if (lw >= 8 and bw % 2) or (lh >= 8 and bh % 2):
                out.append((REFUSE,
                            'CMPR level %d is %dx%d - %dx%d blocks. With an odd '
                            'block count the stored size and the tile grid the '
                            'texture unit reads disagree, and the level decodes '
                            'as garbage. Use rgba8 at this size, which is what '
                            'the shipped converter does.' % (lv, lw, lh, bw, bh)))
                break

    if width % 4 or height % 4:
        out.append((NOTE, '%dx%d is not a multiple of 4; the last block column or '
                    'row is padded from the edge texel' % (width, height)))

    order = {REFUSE: 0, WARN: 1, NOTE: 2}
    out.sort(key=lambda r: order[r[0]])
    return out


def check_file(path):
    """Validate a .wit on disk: header, then length against what the engine allocates."""
    out = []
    size = os.path.getsize(path)
    if size < 32:
        return [(REFUSE, 'shorter than the 32-byte header')], None
    with open(path, 'rb') as f:
        blob = f.read()
    try:
        t = W.Wit(blob)
    except ValueError as e:
        return [(REFUSE, str(e))], None
    out += check_dims(t.width, t.height, t.fmt, t.levels, t.faces)
    want = 32 + t.payload
    if size != want:
        out.append((REFUSE,
                    'file is %d bytes; the header says %d. The engine sizes its '
                    'buffer from the header and reads that many bytes, so a short '
                    'file reads past the end of its own allocation.' % (size, want)))
    if t.b18 != 2:
        out.append((NOTE, 'header byte 18 is %d; every shipped file has 2. '
                    'Nothing reads it.' % t.b18))
    if t.b16:
        out.append((NOTE, 'header byte 16 is %d, so the component split is '
                    'overridden. No shipped file does this.' % t.b16))
    order = {REFUSE: 0, WARN: 1, NOTE: 2}
    out.sort(key=lambda r: order[r[0]])
    return out, t


def worst(findings):
    for sev in (REFUSE, WARN, NOTE):
        if any(s == sev for s, _ in findings):
            return sev
    return None
