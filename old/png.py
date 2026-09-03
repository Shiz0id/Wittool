"""A small PNG reader and writer, so the .wit tools need no image library.

Reads 8-bit non-interlaced greyscale, RGB, palette, grey+alpha and RGBA and
hands back a flat RGBA8 bytearray.  That covers what a texture source is.
"""

import struct
import zlib


def _unfilter(raw, w, h, bpp):
    stride = w * bpp
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                b = prev[i]
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ft != 0:
            raise ValueError('filter type %d' % ft)
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def read(path):
    """-> (width, height, RGBA8 bytearray)."""
    d = open(path, 'rb').read()
    if d[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG: %s' % path)
    p = 8
    idat = bytearray(); plte = None; trns = None
    w = h = depth = ctype = interlace = None
    while p < len(d):
        n, tag = struct.unpack_from('>I4s', d, p)
        body = d[p + 8:p + 8 + n]
        p += 12 + n
        if tag == b'IHDR':
            w, h, depth, ctype, _c, _f, interlace = struct.unpack('>IIBBBBB', body)
        elif tag == b'PLTE':
            plte = body
        elif tag == b'tRNS':
            trns = body
        elif tag == b'IDAT':
            idat += body
        elif tag == b'IEND':
            break
    if depth != 8:
        raise ValueError('bit depth %d: only 8 is supported' % depth)
    if interlace:
        raise ValueError('interlaced PNG is not supported')
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = _unfilter(zlib.decompress(bytes(idat)), w, h, chans)
    out = bytearray(w * h * 4)
    for i in range(w * h):
        s = i * chans
        if ctype == 0:
            v = raw[s]; px = (v, v, v, 255)
        elif ctype == 2:
            px = (raw[s], raw[s + 1], raw[s + 2], 255)
        elif ctype == 3:
            j = raw[s]
            a = trns[j] if (trns and j < len(trns)) else 255
            px = (plte[j * 3], plte[j * 3 + 1], plte[j * 3 + 2], a)
        elif ctype == 4:
            v = raw[s]; px = (v, v, v, raw[s + 1])
        else:
            px = (raw[s], raw[s + 1], raw[s + 2], raw[s + 3])
        out[i * 4:i * 4 + 4] = bytes(px)
    return w, h, out


def write(path, w, h, rgba):
    raw = b''.join(b'\0' + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(t, b):
        return (struct.pack('>I', len(b)) + t + b
                + struct.pack('>I', zlib.crc32(t + b) & 0xFFFFFFFF))
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n'
                           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 6))
                           + chunk(b'IEND', b''))
