"""Untile a .wit level into RGBA8, and write PNGs.

    python tools/wii/witpix.py <file.wit> <out.png> [level] [face] [half]

The tiling is GX's, and is the one thing here that the .dol does not spell out -
it is the texture unit's own addressing.  `witcorpus.py mips` is what pins it:
box-filter level 0 and it has to come out as the stored level 1, which no wrong
tile order or level offset survives.
"""

import struct
import sys
import zlib

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wit as W


def _cmpr_block(b, out, ox, oy, w, h):
    """One 4x4 DXT block, GX flavour: big-endian colours, MSB-first indices."""
    c0, c1 = struct.unpack_from('>HH', b, 0)
    bits = struct.unpack_from('>I', b, 4)[0]
    pal = []
    for c in (c0, c1):
        r = (c >> 11) & 0x1F
        g = (c >> 5) & 0x3F
        bl = c & 0x1F
        pal.append([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (bl << 3) | (bl >> 2), 255])
    if c0 > c1:
        pal.append([(2 * pal[0][i] + pal[1][i]) // 3 for i in range(3)] + [255])
        pal.append([(pal[0][i] + 2 * pal[1][i]) // 3 for i in range(3)] + [255])
    else:
        pal.append([(pal[0][i] + pal[1][i]) // 2 for i in range(3)] + [255])
        pal.append([0, 0, 0, 0])
    for y in range(4):
        for x in range(4):
            idx = (bits >> (30 - 2 * (y * 4 + x))) & 3
            px, py = ox + x, oy + y
            if px < w and py < h:
                out[(py * w + px) * 4:(py * w + px) * 4 + 4] = bytes(pal[idx])


def untile(data, w, h, fmt):
    """-> bytearray of w*h RGBA8."""
    out = bytearray(w * h * 4)
    if fmt == W.CMPR:
        # 8x8 tiles of four 4x4 blocks, the blocks in raster order inside the
        # tile - but a sub-block whose origin is outside the image is not in the
        # file at all.  The level holds ceil(w/4) * ceil(h/4) blocks and stops,
        # which is why a 16x4 level is 32 bytes and not the 64 a padded tile grid
        # would need.  Consume in tile order and skip, or every level under 8
        # texels tall decodes only its left-hand 8 columns.
        p = 0
        for ty in range(0, h, 8):
            for tx in range(0, w, 8):
                for sy in (0, 4):
                    for sx in (0, 4):
                        if tx + sx >= w or ty + sy >= h:
                            continue
                        if p + 8 <= len(data):
                            _cmpr_block(data[p:p + 8], out, tx + sx, ty + sy, w, h)
                        p += 8
        return out
    bw, bh, _sz = W.BLOCK[fmt]
    p = 0
    for ty in range(0, h, bh):
        for tx in range(0, w, bw):
            if fmt == W.RGBA8:
                for i in range(16):
                    x, y = tx + (i & 3), ty + (i >> 2)
                    a, r = data[p + i * 2], data[p + i * 2 + 1]
                    g, b = data[p + 32 + i * 2], data[p + 32 + i * 2 + 1]
                    if x < w and y < h:
                        out[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes((r, g, b, a))
                p += 64
            else:
                for i in range(bw * bh):
                    x, y = tx + (i % bw), ty + (i // bw)
                    if fmt == W.I8:
                        v = data[p + i]
                        px = (v, v, v, 255)
                    elif fmt == W.IA8:
                        a, v = data[p + i * 2], data[p + i * 2 + 1]
                        px = (v, v, v, a)
                    elif fmt == W.RGB565:
                        c = struct.unpack_from('>H', data, p + i * 2)[0]
                        r, g, b = (c >> 11) & 0x1F, (c >> 5) & 0x3F, c & 0x1F
                        px = ((r << 3) | (r >> 2), (g << 2) | (g >> 4),
                              (b << 3) | (b >> 2), 255)
                    else:
                        raise NotImplementedError(W.GXNAME[fmt])
                    if x < w and y < h:
                        out[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(px)
                p += _sz
    return out


def png(path, w, h, rgba):
    raw = b''.join(b'\0' + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(t, d):
        return (struct.pack('>I', len(d)) + t + d
                + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF))
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n'
                           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 6))
                           + chunk(b'IEND', b''))


def decode(t, level=0, face=0, half=0):
    w, h, data = t.level(level, face, half)
    return w, h, untile(data, w, h, t.fmt)


if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]
    lvl = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    face = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    half = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    t = W.read(src)
    w, h, rgba = decode(t, lvl, face, half)
    png(out, w, h, rgba)
    print('%s  %s  level %d -> %s %dx%d' % (src, t, lvl, out, w, h))
