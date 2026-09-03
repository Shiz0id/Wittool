"""Read the Wii main.dol and find who calls what.

The Wii build has no linker map of its own - only the partial reconstruction at
E:/Decomp/recomp/RABAZZ_full.map, which does carry the Nintendo RVL SDK symbols
because those are identifiable by signature. That is enough to apply the same
method as on the 360: the code that consumes a vertex format is the code that
calls GXSetVtxAttrFmt / GXSetVtxDesc / GXSetArray, so find its callers and read
what they do with the file's bytes.

DOL header, all big-endian:

    0x00  u32 textOffset[7]     file offset of each text section
    0x1C  u32 dataOffset[11]
    0x48  u32 textAddress[7]    where it loads
    0x64  u32 dataAddress[11]
    0x90  u32 textSize[7]
    0xAC  u32 dataSize[11]
    0xD8  u32 bssAddress        0xDC u32 bssSize     0xE0 u32 entry

Unlike the 360 image, RVA != file offset here, so everything goes through
va_to_off(). Usage:

    python dol.py sections
    python dol.py xref 0x8049C3FC          # who calls this
    python dol.py dis 0x801234ab 40        # disassemble there
    python dol.py sym GXSetVtxAttrFmt      # look up the reconstructed map
"""

import os
import struct
import sys

DOL = (r"E:/Decomp/Battlefront III Wii r2.91120a Unpacked/"
       r"Battlefront III r2.91120a Unpacked/DATA/sys/main.dol")
MAP = r"E:/Decomp/recomp/RABAZZ_full.map"


class Dol:
    def __init__(self, path=DOL):
        self.d = open(path, 'rb').read()
        off = struct.unpack_from('>18I', self.d, 0x00)
        addr = struct.unpack_from('>18I', self.d, 0x48)
        size = struct.unpack_from('>18I', self.d, 0x90)
        # 7 text then 11 data, in one run of 18 for each field.
        self.sections = [(off[i], addr[i], size[i], 'text' if i < 7 else 'data')
                         for i in range(18) if size[i]]
        self.entry = struct.unpack_from('>I', self.d, 0xE0)[0]

    def va_to_off(self, va):
        for o, a, s, _kind in self.sections:
            if a <= va < a + s:
                return o + (va - a)
        return None

    def off_to_va(self, off):
        for o, a, s, _kind in self.sections:
            if o <= off < o + s:
                return a + (off - o)
        return None

    def u32(self, va):
        o = self.va_to_off(va)
        return struct.unpack_from('>I', self.d, o)[0] if o is not None else None

    def f32(self, va):
        o = self.va_to_off(va)
        return struct.unpack_from('>f', self.d, o)[0] if o is not None else None

    def text_sections(self):
        return [s for s in self.sections if s[3] == 'text']

    def xrefs(self, target):
        """Every `bl` (and `b`) whose branch target is `target`."""
        out = []
        for o, a, s, kind in self.text_sections():
            for i in range(0, s, 4):
                w = struct.unpack_from('>I', self.d, o + i)[0]
                if (w >> 26) != 18:                    # I-form branch
                    continue
                li = w & 0x03FFFFFC
                if li & 0x02000000:                    # sign extend 26 bits
                    li -= 0x04000000
                aa = (w >> 1) & 1
                va = a + i
                dest = li if aa else va + li
                if dest == target:
                    out.append((va, 'bl' if (w & 1) else 'b'))
        return out


def load_map(path=MAP):
    """name -> va, and a sorted (va, size, name) list for reverse lookup."""
    names, table = {}, []
    if not os.path.exists(path):
        return names, table
    for line in open(path, encoding='latin1'):
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            va = int(parts[0], 16)
            size = int(parts[1], 16)
        except ValueError:
            continue
        name = parts[2]
        names[name] = va
        table.append((va, size, name))
    table.sort()
    return names, table


def symbolise(table, va):
    """Nearest preceding symbol, as name+delta."""
    lo, hi = 0, len(table)
    while lo < hi:
        mid = (lo + hi) // 2
        if table[mid][0] <= va:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    base, size, name = table[lo - 1]
    if size and va >= base + size:
        return None
    return '%s+0x%x' % (name, va - base) if va != base else name


if __name__ == '__main__':
    dol = Dol()
    names, table = load_map()
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'sections'

    if cmd == 'sections':
        print('entry 0x%08X' % dol.entry)
        for o, a, s, kind in dol.sections:
            print('  %-4s file 0x%06X  va 0x%08X..0x%08X  %d bytes' % (kind, o, a, a + s, s))
        print('%d symbols in the reconstructed map' % len(names))

    elif cmd == 'sym':
        pat = sys.argv[2].lower()
        for n, va in sorted(names.items(), key=lambda kv: kv[1]):
            if pat in n.lower():
                print('0x%08X  %s' % (va, n))

    elif cmd == 'xref':
        target = int(sys.argv[2], 16) if sys.argv[2].startswith('0x') else names[sys.argv[2]]
        print('callers of 0x%08X %s' % (target, symbolise(table, target) or ''))
        for va, kind in dol.xrefs(target):
            print('  0x%08X  %-2s  %s' % (va, kind, symbolise(table, va) or ''))

    elif cmd == 'dis':
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'xex'))
        import ppc
        ppc.MODE = 'broadway'          # opcode 4 and 56/57/60/61 are paired singles here
        va = int(sys.argv[2], 16)
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 32
        o = dol.va_to_off(va)
        for i in range(n):
            w = struct.unpack_from('>I', dol.d, o + i * 4)[0]
            print('  0x%08X  %08X  %s' % (va + i * 4, w, ppc.dis(w, va + i * 4)))
