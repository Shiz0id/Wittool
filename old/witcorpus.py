"""Verify the .wit reader and writer against the shipped tree.

    python tools/wii/witcorpus.py            # sizes, every file
    python tools/wii/witcorpus.py mips       # level N+1 vs a downsample of level N
    python tools/wii/witcorpus.py roundtrip  # decode, re-encode, compare

`sizes` predicts each file's length from its header alone, using the same
arithmetic main.dol uses to allocate the buffer.  A single wrong field - the
format choice, the level count, the per-level bytes, the cube-map or the paired
CMPR doubling - and the prediction misses.

`mips` is the check with teeth on the tiling. Sizes would still add up if the
tile order or the level offsets were wrong; a level read the wrong way stops
being a blurred copy of the level above it.

`roundtrip` decodes a sample back to RGBA, re-encodes it with the same header
settings, and checks the file comes out the same length with the same header and
an image that still matches.  It is slow (a pure-Python CMPR encoder), so it
takes a fixed seeded sample rather than the whole tree.
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import png as PNG
import wit as W
import witpix
import witwrite

ROOT = r"E:\BF3_R9_Wii\DATA\files\assets\bf\tex_wi_v2"


def walk(root=ROOT):
    for dp, _dirs, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith('.wit'):
                yield os.path.join(dp, fn)


def sizes(root=ROOT):
    ok = 0
    rejected = []
    wrong = []
    stub = []
    kinds = {}
    total = 0
    for p in walk(root):
        total += 1
        try:
            t = W.read(p)
        except ValueError as e:
            rejected.append((p, str(e)))
            continue
        key = '%-6s eng%-2d faces=%d%s' % (W.GXNAME[t.fmt], t.engine_fmt, t.faces,
                                           ' paired' if t.paired else '')
        kinds[key] = kinds.get(key, 0) + 1
        size = os.path.getsize(p)
        if size == 32 + t.payload:
            ok += 1
        elif size == 32:
            stub.append(p)               # a header that promises pixels and ships none
        else:
            wrong.append((p, size, 32 + t.payload))
    print('%d of %d files predicted exactly from the header' % (ok, total))
    for k in sorted(kinds, key=lambda k: -kinds[k]):
        print('    %-28s %d' % (k, kinds[k]))
    print('  %d files the loader itself rejects:' % len(rejected))
    seen = {}
    for p, why in rejected:
        seen[why] = seen.get(why, 0) + 1
    for why in sorted(seen, key=lambda w: -seen[why]):
        print('      %-58s %d' % (why[:58], seen[why]))
    for p in stub:
        print('  truncated in the shipped tree - header only, no pixels: %s'
              % os.path.relpath(p, root))
    if wrong:
        print('  %d size mismatches:' % len(wrong))
        for p, got, want in wrong[:10]:
            print('      %-58s %d, expected %d' % (os.path.relpath(p, root)[:58], got, want))
    return not wrong


def _rgba(t, face=0):
    w, h, c = witpix.decode(t, 0, face, 0)
    if t.paired:
        _w, _h, a = witpix.decode(t, 0, face, 1)
        for i in range(w * h):
            c[i * 4 + 3] = a[i * 4 + 1]           # green, see wit.py
    return w, h, c


def _mode_of(t):
    for name, (bits, alpha, fmt) in witwrite.MODES.items():
        if bits == t.bits and alpha == (1 if t.b19 == 1 else 0) and fmt == t.fmt:
            return name
    return None


def roundtrip(root=ROOT, n=120, seed=11):
    paths = list(walk(root))
    random.seed(seed)
    random.shuffle(paths)
    done = 0
    bad = []
    worst = 0.0
    per_mode = {}
    for p in paths:
        if done >= n:
            break
        try:
            t = W.read(p)
        except ValueError:
            continue
        mode = _mode_of(t)
        if mode is None or t.faces != 1 or t.width * t.height > 128 * 128:
            continue
        w, h, rgba = _rgba(t)
        blob = witwrite.build([(w, h, rgba)], mode=mode, levels=t.levels,
                              normal=bool(t.b17 & 2))
        orig = open(p, 'rb').read()
        again = W.Wit(blob)
        _w, _h, back = _rgba(again)
        err = sum(abs(back[i] - rgba[i]) for i in range(0, len(rgba), 4)) / max(1, w * h)
        worst = max(worst, err)
        per_mode[mode] = per_mode.get(mode, 0) + 1
        if len(blob) != len(orig) or blob[:32] != orig[:32] or err > 24:
            bad.append((p, len(blob), len(orig), blob[:32] == orig[:32], err))
        done += 1
    print('%d textures decoded, re-encoded and decoded again' % done)
    for m in sorted(per_mode):
        print('    %-8s %d' % (m, per_mode[m]))
    print('  worst mean red-channel drift after a full round trip: %.1f of 255' % worst)
    if bad:
        print('  %d failures:' % len(bad))
        for p, a, b, hdr, err in bad[:10]:
            print('      %-52s %d vs %d  header=%s  err=%.1f'
                  % (os.path.relpath(p, root)[:52], a, b, hdr, err))
    else:
        print('  every one kept its length, its header and its image')
    return not bad


def mips(root=ROOT, n=1200, seed=7):
    """Level N+1 has to be a downsample of level N.

    Sizes alone would not catch a wrong tile order or a wrong level offset - the
    file would still be the length the header promises.  This would: a misread
    level is not a blurred copy of its parent.  numpy only, no image library.
    """
    import numpy as np

    def cmpr_image(buf, w, h):
        blocks = len(buf) // 8
        a = np.frombuffer(buf[:blocks * 8], dtype='>u2').reshape(blocks, 4)
        c = a[:, :2].astype(np.uint32)
        r5, g6, b5 = (c >> 11) & 0x1F, (c >> 5) & 0x3F, c & 0x1F
        e = np.stack([(r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4),
                      (b5 << 3) | (b5 >> 2)], axis=2).astype(np.int16)
        four = (c[:, 0] > c[:, 1])[:, None]
        p2 = np.where(four, (2 * e[:, 0] + e[:, 1]) // 3, (e[:, 0] + e[:, 1]) // 2)
        p3 = np.where(four, (e[:, 0] + 2 * e[:, 1]) // 3, 0)
        pal = np.stack([e[:, 0], e[:, 1], p2, p3], axis=1)
        bits = np.frombuffer(buf[:blocks * 8], dtype='>u4').reshape(blocks, 2)[:, 1]
        idx = np.stack([(bits >> (30 - 2 * i)) & 3 for i in range(16)], axis=1)
        tex = np.take_along_axis(pal, idx[:, :, None], axis=1).reshape(blocks, 4, 4, 3)
        img = np.zeros((h, w, 3), np.int16)
        k = 0
        for ty in range(0, h, 8):
            for tx in range(0, w, 8):
                for sy in (0, 4):
                    for sx in (0, 4):
                        y0, x0 = ty + sy, tx + sx
                        if x0 >= w or y0 >= h:
                            continue          # not in the file, see witpix.untile
                        if k >= blocks:
                            break
                        dy, dx = min(4, h - y0), min(4, w - x0)
                        img[y0:y0 + dy, x0:x0 + dx] = tex[k, :dy, :dx]
                        k += 1
        return img

    def box(img):
        h, w, _ = img.shape
        return (img[0:h:2, 0:w:2] + img[1:h:2, 0:w:2]
                + img[0:h:2, 1:w:2] + img[1:h:2, 1:w:2]) // 4

    paths = list(walk(root))
    random.seed(seed)
    random.shuffle(paths)
    # Every consecutive pair, not just 0 -> 1.  The deep levels are the ones that
    # go narrower than a tile and so the ones that catch a wrong block order;
    # an earlier version of this check looked only at level 0 of textures at
    # least 16 texels square and missed exactly that.
    wide, narrow, sharp, ctl, done = [], [], [], [], 0
    for p in paths:
        if done >= n:
            break
        try:
            t = W.read(p)
        except ValueError:
            continue
        if t.fmt != W.CMPR or t.levels < 2:
            continue
        used = False
        for lv in range(t.levels - 1):
            w0, h0, d0 = t.level(lv)
            w1, h1, d1 = t.level(lv + 1)
            if w0 < 2 or h0 < 2 or (w1, h1) != (w0 // 2, h0 // 2):
                continue
            a, b = cmpr_image(d0, w0, h0), cmpr_image(d1, w1, h1)
            e = np.abs(box(a) - b).mean()
            (narrow if (w1 < 8 or h1 < 8) else wide).append(e)
            # The pairs that actually separate the two candidate block orders:
            # long and thin, so a tile holds in-image and out-of-image sub-blocks
            # side by side.  Reading them without the skip gives mean 40.2 here.
            if (w1 >= 16 and h1 < 8) or (h1 >= 16 and w1 < 8):
                sharp.append(e)
            if w1 >= 8 and h1 >= 8:
                ctl.append(np.abs(a[:h1, :w1] - b).mean())
            used = True
        done += 1 if used else 0
    wd, nd, sh, c = (np.array(wide), np.array(narrow), np.array(sharp), np.array(ctl))
    print('%d CMPR textures, every consecutive level pair' % done)
    print('  %5d pairs at 8x8 or larger      : mean %.2f  median %.2f  p95 %.2f  of 255'
          % (len(wd), wd.mean(), np.median(wd), np.percentile(wd, 95)))
    print('  %5d pairs narrower than a tile  : mean %.2f  median %.2f  p95 %.2f'
          % (len(nd), nd.mean(), np.median(nd), np.percentile(nd, 95)))
    print('  %5d long and thin, block order  : mean %.2f  (40.21 with the skip removed)'
          % (len(sh), sh.mean()))
    print('  control, a level against the top-left quarter of its parent: mean %.2f' % c.mean())
    print('  under 8: %.1f%%   under 16: %.1f%%'
          % (100 * (wd < 8).mean(), 100 * (wd < 16).mean()))
    return (wd.mean() < 8 and nd.mean() < 12 and sh.mean() < 12
            and c.mean() > 4 * wd.mean())


def synthetic():
    """Every mode, plus a cube map, built from scratch and read back."""
    w = h = 32
    px = bytearray()
    for y in range(h):
        for x in range(w):
            px += bytes((x * 8 & 0xFF, y * 8 & 0xFF, (x ^ y) * 4 & 0xFF,
                         255 if (x // 8 + y // 8) % 2 else 64))
    ok = True
    for mode in sorted(witwrite.MODES):
        blob = witwrite.build([(w, h, px)], mode=mode)
        t = W.Wit(blob)
        good = len(blob) == 32 + t.payload
        print('    %-7s -> %-40s %d bytes  %s' % (mode, t, len(blob), 'ok' if good else 'BAD'))
        ok = ok and good
    blob = witwrite.build([(w, h, px)] * 6, mode='cmpr', cube=True)
    t = W.Wit(blob)
    good = len(blob) == 32 + t.payload and t.faces == 6
    print('    %-7s -> %-40s %d bytes  %s' % ('cube', t, len(blob), 'ok' if good else 'BAD'))
    return ok and good


if __name__ == '__main__':
    what = sys.argv[1] if len(sys.argv) > 1 else 'sizes'
    if what == 'sizes':
        raise SystemExit(0 if sizes() else 1)
    if what == 'mips':
        raise SystemExit(0 if mips() else 1)
    if what == 'roundtrip':
        print('synthetic:')
        a = synthetic()
        print('shipped:')
        b = roundtrip()
        raise SystemExit(0 if (a and b) else 1)
    print(__doc__)
    raise SystemExit(2)
