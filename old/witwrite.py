"""Build a .wit from RGBA8 pixels - the inverse of tools/wii/wit.py.

The header and the payload layout are whatever main.dol will read back; wit.py
says where each rule comes from.  The only choice a caller makes is which of the
format pairs to ask for, because the file names a source bit depth and an alpha
flag rather than a GX format:

    cmpr    24 bits, alpha 1   one CMPR chain          RGB, no alpha
    cmpra   32 bits, alpha 1   two CMPR chains         RGB plus an alpha mask
    rgb565  24 bits, alpha 0   one RGB565 chain
    rgba8   32 bits, alpha 0   one RGBA8 chain
    i8       8 bits, alpha 0   one I8 chain
    ia8     16 bits, alpha 0   one IA8 chain

cmpra is the shipped default for anything with alpha: CMPR carries one bit of
it, so the converter puts the mask in a second CMPR chain of the same shape.
The engine reaches that through engine format 9 at 0x803EC02C.

    python tools/wii/witwrite.py <in.png> <out.wit> [mode] [levels]
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wit as W

MODES = {
    'cmpr':   (24, 1, W.CMPR),
    'cmpra':  (32, 1, W.CMPR),
    'rgb565': (24, 0, W.RGB565),
    'rgba8':  (32, 0, W.RGBA8),
    'i8':     (8, 0, W.I8),
    'ia8':    (16, 0, W.IA8),
}

LUMA = (77, 150, 29)


def box_half(rgba, w, h):
    """One mip step, averaging 2x2 - a dimension already at 1 stays at 1."""
    nw, nh = max(w >> 1, 1), max(h >> 1, 1)
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        y0 = min(y * 2, h - 1)
        y1 = min(y0 + 1, h - 1)
        for x in range(nw):
            x0 = min(x * 2, w - 1)
            x1 = min(x0 + 1, w - 1)
            a = (y0 * w + x0) * 4
            b = (y0 * w + x1) * 4
            c = (y1 * w + x0) * 4
            d = (y1 * w + x1) * 4
            o = (y * nw + x) * 4
            for k in range(4):
                out[o + k] = (rgba[a + k] + rgba[b + k] + rgba[c + k] + rgba[d + k] + 2) // 4
    return out


def full_chain(rgba, w, h, levels):
    chain = [(w, h, rgba)]
    for _ in range(levels - 1):
        rgba = box_half(rgba, w, h)
        w, h = max(w >> 1, 1), max(h >> 1, 1)
        chain.append((w, h, rgba))
    return chain


def to565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def from565(c):
    r, g, b = (c >> 11) & 0x1F, (c >> 5) & 0x3F, c & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def cmpr_block(px):
    """px: 16 (r, g, b) tuples -> 8 bytes, GX order (BE endpoints, MSB-first).

    Always the four-colour mode, so c0 > c1.  The three-colour mode spends a
    palette entry on transparency, and alpha never lives in this chain.
    """
    mn = [min(p[i] for p in px) for i in range(3)]
    mx = [max(p[i] for p in px) for i in range(3)]
    axis = [mx[i] - mn[i] for i in range(3)]
    if max(axis) == 0:
        c = to565(*px[0])
        return struct.pack('>HHI', c, c, 0)
    dots = [p[0] * axis[0] + p[1] * axis[1] + p[2] * axis[2] for p in px]
    lo = px[dots.index(min(dots))]
    hi = px[dots.index(max(dots))]
    c0, c1 = to565(*hi), to565(*lo)
    if c0 < c1:
        c0, c1 = c1, c0
    if c0 == c1:
        return struct.pack('>HHI', c0, c1, 0)
    e0, e1 = from565(c0), from565(c1)
    pal = (e0, e1,
           tuple((2 * e0[i] + e1[i]) // 3 for i in range(3)),
           tuple((e0[i] + 2 * e1[i]) // 3 for i in range(3)))
    bits = 0
    for i, p in enumerate(px):
        best = 0
        bestd = None
        for k in range(4):
            q = pal[k]
            dd = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2
            if bestd is None or dd < bestd:
                bestd, best = dd, k
        bits |= best << (30 - 2 * i)
    return struct.pack('>HHI', c0, c1, bits)


def fetch(rgba, w, h, x, y):
    """Clamp to the edge - a level narrower than a block still fills one."""
    x = x if x < w else w - 1
    y = y if y < h else h - 1
    o = (y * w + x) * 4
    return rgba[o], rgba[o + 1], rgba[o + 2], rgba[o + 3]


def tile_level(rgba, w, h, fmt, alpha_as_grey=False):
    """One level, tiled the way the texture unit reads it."""
    out = bytearray()
    if fmt == W.CMPR:
        for ty in range(0, h, 8):
            for tx in range(0, w, 8):
                for sy in (0, 4):
                    for sx in (0, 4):
                        if tx + sx >= w or ty + sy >= h:
                            continue
                        px = []
                        for y in range(4):
                            for x in range(4):
                                r, g, b, a = fetch(rgba, w, h, tx + sx + x, ty + sy + y)
                                px.append((a, a, a) if alpha_as_grey else (r, g, b))
                        out += cmpr_block(px)
    else:
        bw, bh, _size = W.BLOCK[fmt]
        for ty in range(0, h, bh):
            for tx in range(0, w, bw):
                if fmt == W.RGBA8:
                    ar = bytearray()
                    gb = bytearray()
                    for i in range(16):
                        r, g, b, a = fetch(rgba, w, h, tx + (i & 3), ty + (i >> 2))
                        ar += bytes((a, r))
                        gb += bytes((g, b))
                    out += ar + gb
                else:
                    for i in range(bw * bh):
                        r, g, b, a = fetch(rgba, w, h, tx + (i % bw), ty + (i // bw))
                        if fmt == W.I8:
                            out += bytes(((r * LUMA[0] + g * LUMA[1] + b * LUMA[2]) >> 8,))
                        elif fmt == W.IA8:
                            out += bytes((a, (r * LUMA[0] + g * LUMA[1] + b * LUMA[2]) >> 8))
                        elif fmt == W.RGB565:
                            out += struct.pack('>H', to565(r, g, b))
                        else:
                            raise NotImplementedError(W.GXNAME[fmt])
    if len(out) < 32:
        out += b'\0' * (32 - len(out))       # the 32-byte floor a level never goes under
    return bytes(out)


max_levels = W.max_levels          # it belongs to the format, not the writer


def build(faces, mode='cmpra', levels=None, cube=False, normal=False):
    """faces: [(w, h, rgba)] - one entry, or six for a cube map.

    `normal` sets bit 1 of header byte 17.  Every file that carries it is a
    normal or refraction map, but this build's .wit reader looks only at bit 0
    (0x803EC7F0, andi 1), so the bit changes nothing about how the file loads;
    it is written only to reproduce the shipped headers byte for byte.
    """
    if mode not in MODES:
        raise ValueError('mode must be one of: %s' % ', '.join(sorted(MODES)))
    bits, alpha, fmt = MODES[mode]
    if cube and len(faces) != 6:
        raise ValueError('a cube map needs six faces')
    if not cube and len(faces) != 1:
        raise ValueError('a plain texture takes one face')
    w, h = faces[0][0], faces[0][1]
    top = max_levels(w, h)
    if levels is None:
        # Non-power-of-two cannot mip: halving stops being exact, and the shipped
        # tree agrees - all 19 of its NPOT textures are single-level.
        levels = 1 if (w & (w - 1) or h & (h - 1)) else top
    else:
        levels = max(1, min(levels, top))

    import witcheck
    bad = [m for s, m in witcheck.check_dims(w, h, fmt, levels, 6 if cube else 1)
           if s == witcheck.REFUSE]
    if bad:
        raise ValueError('this texture will not load:\n  - ' + '\n  - '.join(bad))

    body = bytearray()
    for fw, fh, rgba in faces:
        if (fw, fh) != (w, h):
            raise ValueError('every face must be %dx%d' % (w, h))
        chain = full_chain(rgba, fw, fh, levels)
        halves = (False, True) if mode == 'cmpra' else (False,)
        for grey in halves:
            for lw, lh, lv in chain:
                body += tile_level(lv, lw, lh, fmt, alpha_as_grey=grey)

    hdr = struct.pack('>IIII', w, h, bits, levels - 1)
    hdr += bytes((0, (1 if cube else 0) | (2 if normal else 0), 2, alpha))
    hdr += struct.pack('>III', 1, 0, 0)
    blob = bytes(hdr) + bytes(body)

    # The engine sizes the buffer from the header alone.  Disagree with it and
    # the file is wrong, so check rather than trust.
    expect = 32 + W.Wit(blob).payload
    if len(blob) != expect:
        raise AssertionError('built %d bytes; main.dol expects %d' % (len(blob), expect))
    return blob


def main(argv):
    import png as PNG
    if len(argv) < 3:
        print(__doc__)
        return 2
    src, dst = argv[1], argv[2]
    mode = argv[3] if len(argv) > 3 else 'cmpra'
    levels = int(argv[4]) if len(argv) > 4 else None
    w, h, rgba = PNG.read(src)
    blob = build([(w, h, rgba)], mode=mode, levels=levels)
    open(dst, 'wb').write(blob)
    print('%s -> %s  %s  %d bytes' % (os.path.basename(src), dst, W.Wit(blob), len(blob)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
