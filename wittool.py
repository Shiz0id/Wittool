"""wittool - work with Star Wars Battlefront III (Wii, R9) `.wit` textures.

    python tools/wii/wittool.py <command> [args]

    info    <file.wit>...              header, format and anything suspect
    check   <file.wit|dir>...          validate against what the engine accepts
    decode  <in.wit> <out.png>         one level to PNG, colour and alpha combined
    dump    <in.wit> <outdir>          every level and face, as PNGs
    encode  <in.png> <out.wit>         compile a PNG
    replace <orig.wit> <new.png> <out.wit>
                                       recompile keeping the original's settings
    cube    <out.wit> <+x> <-x> <+y> <-y> <+z> <-z>
                                       six PNGs into one cube map
    xref    <ob.war> [--root DIR]      which textures a model uses
    find    <dir> [filters]            search a texture tree

Formats (`--mode`, encode/cube):

    cmpr    RGB, 4 bpp, no alpha           rgba8   RGBA, 32 bpp, exact
    cmpra   RGB + alpha mask, 8 bpp        i8      greyscale, 8 bpp
    rgb565  RGB, 16 bpp, no alpha          ia8     grey + alpha, 16 bpp

`cmpra` is the default and is what the game uses for almost everything with
alpha: CMPR holds one bit of alpha, so the converter writes a second CMPR chain
carrying the mask as grey.  Do not reach for CMPR's own punch-through mode -
across 180 million shipped blocks it is used in 0.009% of them.

Where the files go: `<game>/DATA/files/assets/bf/tex_wi_v2/<path>.wit`, loose.
The `.pak` files beside the pools are empty PCK2 stubs, so nothing overrides a
loose file.

The trap worth knowing before you start: anything over 1024 in either dimension
is not rejected, it is silently replaced with `misctex/generic/fill`, a 16x16
flat white.  Your surface goes blank and nothing is logged.  `check` catches it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import png as PNG
import wit as W
import witcheck
import witpix
import witwrite
import witxref

DEFAULT_ROOT = r"E:\BF3_R9_Wii\DATA\files\assets\bf\tex_wi_v2"


def _opt(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        v = argv[i + 1]
        del argv[i:i + 2]
        return v
    return default


def _flag(argv, name):
    if name in argv:
        argv.remove(name)
        return True
    return False


def _rgba(t, face=0):
    """Colour with the paired alpha chain folded into A."""
    w, h, c = witpix.decode(t, 0, face, 0)
    if t.paired:
        _w, _h, a = witpix.decode(t, 0, face, 1)
        for i in range(w * h):
            # Green. TEV stage 1 samples the alpha chain through swap table 3,
            # which broadcasts GREEN into all four channels, so GX_CA_TEXA is
            # the green channel - see wit.py.
            c[i * 4 + 3] = a[i * 4 + 1]
    return w, h, c


def _report(findings, indent='    '):
    for sev, msg in findings:
        print('%s%-7s %s' % (indent, sev, msg))


# --------------------------------------------------------------------------- info

def cmd_info(argv):
    for p in argv:
        print(p)
        try:
            t = W.read(p)
        except (ValueError, OSError) as e:
            print('    unreadable: %s' % e)
            continue
        print('    %dx%d  %s  %d level%s  %d face%s%s'
              % (t.width, t.height, W.GXNAME[t.fmt], t.levels,
                 '' if t.levels == 1 else 's', t.faces,
                 '' if t.faces == 1 else 's',
                 '  paired alpha chain' if t.paired else ''))
        print('    source %d bits, alpha flag %d, engine format %d'
              % (t.bits, t.b19, t.engine_fmt))
        mode = None
        for name, (bits, alpha, fmt) in witwrite.MODES.items():
            if bits == t.bits and alpha == (1 if t.b19 == 1 else 0) and fmt == t.fmt:
                mode = name
        print('    rebuild with: --mode %s --levels %d%s%s'
              % (mode or '(no matching mode)', t.levels,
                 ' --cube' if t.faces == 6 else '',
                 ' --normal' if (t.b17 & 2) else ''))
        print('    %d bytes on disk, %d expected' % (os.path.getsize(p), 32 + t.payload))
        for lv in range(t.levels):
            lw, lh = W.level_dims(t.width, t.height, lv)
            print('      level %d  %4dx%-4d  %6d bytes at +0x%X'
                  % (lv, lw, lh, W.level_bytes(lw, lh, t.fmt),
                     32 + t.level_offset(lv)))
        findings, _ = witcheck.check_file(p)
        if findings:
            _report(findings)
    return 0


# -------------------------------------------------------------------------- check

def cmd_check(argv):
    paths = []
    for a in argv:
        if os.path.isdir(a):
            for dp, _d, fns in os.walk(a):
                paths += [os.path.join(dp, f) for f in fns if f.lower().endswith('.wit')]
        else:
            paths.append(a)
    bad = 0
    for p in paths:
        findings, _t = witcheck.check_file(p)
        sev = witcheck.worst(findings)
        if sev == witcheck.REFUSE:
            bad += 1
        if findings:
            print('%s' % p)
            _report(findings)
    print('%d file%s checked, %d the engine would reject or replace'
          % (len(paths), '' if len(paths) == 1 else 's', bad))
    return 1 if bad else 0


# ------------------------------------------------------------------------- decode

def cmd_decode(argv):
    level = int(_opt(argv, '--level', '0'))
    face = int(_opt(argv, '--face', '0'))
    alpha_only = _flag(argv, '--alpha')
    src, dst = argv[0], argv[1]
    t = W.read(src)
    if alpha_only:
        if not t.paired:
            print('%s has no alpha chain' % src)
            return 1
        w, h, px = witpix.decode(t, level, face, 1)
    elif level == 0:
        w, h, px = _rgba(t, face)
    else:
        w, h, px = witpix.decode(t, level, face, 0)
        if t.paired:
            _w, _h, a = witpix.decode(t, level, face, 1)
            for i in range(w * h):
                px[i * 4 + 3] = a[i * 4 + 1]      # green, see wit.py
    PNG.write(dst, w, h, px)
    print('%s level %d face %d -> %s  %dx%d' % (src, level, face, dst, w, h))
    return 0


def cmd_dump(argv):
    src, outdir = argv[0], argv[1]
    t = W.read(src)
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    n = 0
    for face in range(t.faces):
        for lv in range(t.levels):
            for half in range(2 if t.paired else 1):
                w, h, px = witpix.decode(t, lv, face, half)
                name = '%s_f%d_l%d_%s.png' % (stem, face, lv,
                                              'alpha' if half else 'colour')
                PNG.write(os.path.join(outdir, name), w, h, px)
                n += 1
    print('%s -> %d PNGs in %s' % (src, n, outdir))
    return 0


# ------------------------------------------------------------------------- encode

def _encode(pngs, dst, mode, levels, cube, normal):
    faces = [PNG.read(p) for p in pngs]
    blob = witwrite.build(faces, mode=mode, levels=levels, cube=cube, normal=normal)
    open(dst, 'wb').write(blob)
    t = W.Wit(blob)
    print('%s  %dx%d %s %d level%s%s  %d bytes'
          % (dst, t.width, t.height, W.GXNAME[t.fmt], t.levels,
             '' if t.levels == 1 else 's',
             ' cube' if t.faces == 6 else '', len(blob)))
    findings, _ = witcheck.check_file(dst)
    if findings:
        _report(findings)
    return 0


def cmd_encode(argv):
    mode = _opt(argv, '--mode', 'cmpra')
    levels = _opt(argv, '--levels')
    normal = _flag(argv, '--normal')
    return _encode([argv[0]], argv[1], mode,
                   int(levels) if levels else None, False, normal)


def cmd_cube(argv):
    mode = _opt(argv, '--mode', 'cmpr')
    levels = _opt(argv, '--levels')
    dst, pngs = argv[0], argv[1:7]
    if len(pngs) != 6:
        print('a cube map needs six PNGs, in GX order: +X -X +Y -Y +Z -Z')
        return 2
    return _encode(pngs, dst, mode, int(levels) if levels else None, True, False)


def cmd_replace(argv):
    """Recompile a PNG using the settings of the file it is replacing."""
    orig, src, dst = argv[0], argv[1], argv[2]
    t = W.read(orig)
    mode = None
    for name, (bits, alpha, fmt) in witwrite.MODES.items():
        if bits == t.bits and alpha == (1 if t.b19 == 1 else 0) and fmt == t.fmt:
            mode = name
    if mode is None:
        print('%s uses a combination with no writer mode (%d bits, alpha %d, %s)'
              % (orig, t.bits, t.b19, W.GXNAME[t.fmt]))
        return 1
    w, h, _px = PNG.read(src)
    if (w, h) != (t.width, t.height):
        print('note: %s is %dx%d, the original is %dx%d - the game does not care, '
              'but the memory budget was set for the original'
              % (src, w, h, t.width, t.height))
    print('matching %s: --mode %s --levels %d%s' % (os.path.basename(orig), mode,
                                                    t.levels,
                                                    ' --normal' if t.b17 & 2 else ''))
    return _encode([src], dst, mode, t.levels, t.faces == 6, bool(t.b17 & 2))


# --------------------------------------------------------------------------- xref

def cmd_xref(argv):
    root = _opt(argv, '--root', DEFAULT_ROOT)
    tex_root = os.path.join(root, 'textures')
    obs = []
    for a in argv:
        if os.path.isdir(a):
            for dp, _d, fns in os.walk(a):
                obs += [os.path.join(dp, f) for f in fns if f.lower() == 'ob.war']
        else:
            obs.append(a)
    for ob in obs:
        strong, weak, total = witxref.model_textures(ob, tex_root)
        print('%s   (%d ids in %s)' % (ob, total, tex_root))
        for off, v, fn in strong:
            print('    ob+0x%04X  %08x  textures/%s   %s'
                  % (off, v, fn, witxref.describe(tex_root, fn)))
        if not strong:
            print('    no texture ids - this model may name its textures by path instead')
        for off, v, fn in weak:
            print('    ob+0x%04X  %08x  textures/%s   (id under 0x%X, as likely to be '
                  'an ordinary small integer)' % (off, v, fn, witxref.MIN_TRUSTED))
    return 0


# --------------------------------------------------------------------------- find

def cmd_find(argv):
    want_size = _opt(argv, '--size')
    want_fmt = _opt(argv, '--format')
    want_cube = _flag(argv, '--cube')
    want_paired = _flag(argv, '--paired')
    over = _flag(argv, '--rejected')
    root = argv[0] if argv else DEFAULT_ROOT
    n = 0
    for dp, _d, fns in os.walk(root):
        for fn in fns:
            if not fn.lower().endswith('.wit'):
                continue
            p = os.path.join(dp, fn)
            try:
                t = W.read(p)
            except (ValueError, OSError) as e:
                if over:
                    print('%-58s the loader refuses it: %s'
                          % (os.path.relpath(p, root), e))
                    n += 1
                continue
            if want_size and '%dx%d' % (t.width, t.height) != want_size:
                continue
            if want_fmt and W.GXNAME[t.fmt].lower() != want_fmt.lower():
                continue
            if want_cube and t.faces != 6:
                continue
            if want_paired and not t.paired:
                continue
            if over and not (t.width > witcheck.MAX_DIMENSION
                             or t.height > witcheck.MAX_DIMENSION):
                continue
            print('%-58s %4dx%-4d %-7s %d lv%s%s'
                  % (os.path.relpath(p, root), t.width, t.height, W.GXNAME[t.fmt],
                     t.levels, ' cube' if t.faces == 6 else '',
                     ' paired' if t.paired else ''))
            n += 1
    print('%d match%s' % (n, '' if n == 1 else 'es'))
    return 0


COMMANDS = {
    'info': cmd_info, 'check': cmd_check, 'decode': cmd_decode, 'dump': cmd_dump,
    'encode': cmd_encode, 'replace': cmd_replace, 'cube': cmd_cube,
    'xref': cmd_xref, 'find': cmd_find,
}


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0 if len(argv) > 1 else 2
    cmd = COMMANDS.get(argv[1])
    if cmd is None:
        print('unknown command %r; try --help' % argv[1])
        return 2
    try:
        return cmd(argv[2:])
    except (ValueError, OSError, IndexError) as e:
        print('%s: %s' % (argv[1], e))
        return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
