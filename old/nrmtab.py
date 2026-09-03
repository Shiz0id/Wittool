"""Extract the engine's built-in unit-normal table out of the Wii main.dol.

`setupVertexArrays` at 0x803E2FD0 points GX_VA_NRM and GX_VA_NBT at
0x806FCED8 whenever a part's normal array offset (geom+0x10) is zero, which is
almost all of them - only cloth ships normals of its own. The table runs up to
0x8070292C, where the vertex descriptor table starts, so it holds 3854 entries
of three s16 at 1/16384 (GX_S16 frac 14, from the GXSetVtxAttrFmt calls at
0x803DCBC0). Every one of them is a unit vector, and the largest normal index
in the shipped tree is 3853.

It is engine data rather than asset data, so it is extracted rather than
committed - the same treatment build/bf_gold.pe gets:

    python tools/wii/nrmtab.py                  # -> build/wii_normals.bin
    python tools/wii/nrmtab.py <out.bin>
"""

import math
import os
import struct
import sys

from dol import Dol

TABLE_VA = 0x806FCED8
TABLE_ENTRIES = 3854
NORMAL_SCALE = 1.0 / 16384.0


def extract(path=None):
    d = Dol()
    off = d.va_to_off(TABLE_VA)
    if off is None:
        raise SystemExit('0x%08X is not in main.dol' % TABLE_VA)
    blob = d.d[off:off + TABLE_ENTRIES * 6]

    # It is only the right table if every entry is a unit vector.
    worst = 0.0
    for i in range(TABLE_ENTRIES):
        x, y, z = struct.unpack_from('>3h', blob, i * 6)
        n = math.sqrt(x * x + y * y + z * z) * NORMAL_SCALE
        worst = max(worst, abs(n - 1.0))
    if worst > 0.01:
        raise SystemExit('entries are not unit vectors (worst %.4f) - wrong address?' % worst)

    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, '..', '..', 'build', 'wii_normals.bin')
    path = os.path.abspath(path)
    with open(path, 'wb') as f:
        f.write(blob)
    print('%d normals -> %s (%d bytes), worst |n|-1 = %.5f'
          % (TABLE_ENTRIES, path, len(blob), worst))
    return path


if __name__ == '__main__':
    extract(sys.argv[1] if len(sys.argv) > 1 else None)
