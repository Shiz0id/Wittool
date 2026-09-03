"""Read and write the Wii R9 texture format, `.wit` (pool `tex_wi_v2`).

Everything here is what `main.dol` does, not what the bytes look like:

    0x803EE2B0  loadWit            reads the file, hands the blob to
    0x803EC7C8  witBlobToTexture   pulls the header bytes apart
    0x803EBE94  createTexture      picks the format and sizes the buffer
    0x803EBD50  chooseFormat       (componentBytes, componentCount, alpha) -> GX format
    0x8049E8AC  GXGetTexBufferSize the tiled mip-chain size

Header, 32 bytes, big-endian, data immediately after:

    +0x00  u32  width
    +0x04  u32  height
    +0x08  u32  source bits per pixel - 8, 16, 24 or 32
    +0x0C  u32  maxLod: the chain holds maxLod + 1 levels
    +0x10  u32  flags, read as four bytes:
                 [16] componentBytes override; 0 means "derive from +0x08"
                 [17] bit 0 = cube map, six faces back to back
                 [18] always 2 in the shipped tree, unread by the loader
                 [19] alpha: 1 selects the alpha-capable format of the pair
    +0x14  u32  image count. `witBlobToTexture` REJECTS anything above 1
                (0x803EC800: cmplwi 1 / bgt to the bare return at 0x803EC894),
                so the 33 files that carry 6 cannot be loaded by this build.
    +0x18  u32  0
    +0x1C  u32  0

The format is chosen from a component split rather than named outright.  With
byte 16 clear - which is every shipped file - componentBytes is just
`bits >> 3` and componentCount is 1:

    8 bits  -> GX_TF_I8       16 bits -> GX_TF_IA8
    24 bits -> GX_TF_CMPR if byte 19 is 1, else GX_TF_RGB565
    32 bits -> GX_TF_CMPR **twice** if byte 19 is 1, else GX_TF_RGBA8

That doubling is engine format 9 at 0x803EC02C (`slwi r22, r3, 1`): CMPR carries
only one bit of alpha, so a 32-bit source is stored as two CMPR images, the
colour chain followed by a second chain of the same shape.

**The alpha chain is read through its GREEN channel.**  The two chains get two
GXTexObjs in one 72-byte slot - colour at +8, alpha at +40 pointing at
`base + chainBytes` (0x803EC3B4) - and `bindTexture` (0x803EB9F0) puts them on
GX_TEXMAP(2n) and GX_TEXMAP(2n+1).  The TEV setup at 0x803DAB54 asks
`currentSlotHasAlphaChain()` (0x803EBB24) and, when it says yes, emits a second
stage:

    GXSetTevSwapModeTable(3, GREEN, GREEN, GREEN, GREEN)   0x803DAC60
    GXSetTevSwapMode(stage 1, ras 0, tex 3)                0x803DAC48
    GXSetTevColorIn(stage 1, ZERO, ZERO, ZERO, CPREV)      0x803DAC84
    GXSetTevAlphaIn(stage 1, ZERO, RASA, TEXA, ZERO)       0x803DACA8
    GXSetTevOrder(stage 1, GX_TEXCOORD0, GX_TEXMAP1, GX_COLOR0A0)  0x803DACC8

Swap table 3 broadcasts green into all four channels, so the stage's GX_CA_TEXA
*is* the alpha texture's green.  Stage 0 sets its own alpha to ZERO on this path
- CMPR's alpha is meaningless, it is always opaque in the four-colour mode - and
stage 1 supplies alpha as `RASA * TEXA` while passing the colour through.

Green because RGB565 spends six bits there against five on red and blue, so a
grey mask read from green keeps one more bit.  The shipped data agrees: over
296,323,712 alpha-chain texels, |G - R| is at most 4 for 100% of them and
|G - B| for 97.4%, means 0.21 and 0.48 - the same grey quantised at two
different depths.

A level is stored as whole blocks, ceil'd, with a floor of one 32-byte GX tile.
For CMPR that block is the 4x4/8-byte DXT block, not GX's padded 8x8 tile - the
two only differ when a dimension is under 8 or not a multiple of 8, and the
corpus is decisive there (`aw_lightning01.wit`, 128x32 with four levels, ends in
32 bytes where a padded tile would need 64).

Verified against all 10,317 files under
E:/BF3_R9_Wii/DATA/files/assets/bf/tex_wi_v2 - see `witcorpus.py`.
"""

import struct

# GX texture format numbers, as passed to GXInitTexObj.
I8, IA4, IA8, RGB565, RGB5A3, RGBA8, CMPR = 1, 2, 3, 4, 5, 6, 14
I4, C4, C8, C14X2, Z24X8 = 0, 8, 9, 10, 22

GXNAME = {I4: 'I4', I8: 'I8', IA4: 'IA4', IA8: 'IA8', RGB565: 'RGB565',
          RGB5A3: 'RGB5A3', RGBA8: 'RGBA8', C4: 'C4', C8: 'C8',
          C14X2: 'C14X2', CMPR: 'CMPR', Z24X8: 'Z24X8'}

# Tile geometry, from the jump table at 0x807202C0 that GXGetTexBufferSize
# dispatches through: (log2 tile width, log2 tile height).
SHIFT = {I4: (3, 3), I8: (3, 2), IA4: (3, 2), IA8: (2, 2), RGB565: (2, 2),
         RGB5A3: (2, 2), RGBA8: (2, 2), C4: (3, 3), C8: (3, 2),
         C14X2: (2, 2), CMPR: (3, 3), Z24X8: (2, 2)}

# What a level actually occupies on disk: (block width, block height, bytes).
BLOCK = {I4: (8, 8, 32), I8: (8, 4, 32), IA4: (8, 4, 32), IA8: (4, 4, 32),
         RGB565: (4, 4, 32), RGB5A3: (4, 4, 32), RGBA8: (4, 4, 64),
         CMPR: (4, 4, 8), Z24X8: (4, 4, 64)}


def choose_format(comp_bytes, comp_count, alpha):
    """0x803EBD50. Returns (engineFormat, gxFormat), or None where it fails."""
    if comp_bytes == -1:
        return (1, I4) if comp_count == 0 else (2, I8)
    if comp_bytes == 1:
        if comp_count == 1:
            return (3, I8)
        if comp_count == 4:
            return (13, Z24X8)
        return (0, I4)
    if comp_bytes == 2:
        return (5, IA8) if comp_count == 1 else (4, IA4)
    if comp_bytes == 3:
        return (8, CMPR) if alpha else (6, RGB565)
    if comp_bytes == 4:
        return (9, CMPR) if alpha else (7, RGBA8)
    return None


def level_bytes(w, h, fmt):
    bw, bh, size = BLOCK[fmt]
    return max(((w + bw - 1) // bw) * ((h + bh - 1) // bh) * size, 32)


def level_dims(w, h, level):
    for _ in range(level):
        w = w >> 1 if w > 1 else 1
        h = h >> 1 if h > 1 else 1
    return w, h


def max_levels(w, h):
    """How many levels a chain can hold before both dimensions reach 1."""
    n = 1
    while w > 1 or h > 1:
        w, h = max(w >> 1, 1), max(h >> 1, 1)
        n += 1
    return n


def chain_bytes(w, h, fmt, levels):
    """Sum of the stored levels, in GXGetTexBufferSize's loop shape."""
    total = 0
    for _ in range(levels):
        total += level_bytes(w, h, fmt)
        if w <= 1 and h <= 1:
            break
        w = w >> 1 if w > 1 else 1
        h = h >> 1 if h > 1 else 1
    return total


class Wit(object):
    """A parsed .wit. `images` is faces * (2 if paired else 1) mip chains."""

    def __init__(self, blob):
        if len(blob) < 32:
            raise ValueError('short .wit: %d bytes' % len(blob))
        (self.width, self.height, self.bits, self.max_lod,
         _flags, self.count, r6, r7) = struct.unpack_from('>8I', blob, 0)
        self.b16, self.b17, self.b18, self.b19 = blob[16], blob[17], blob[18], blob[19]
        if self.count > 1:
            raise ValueError('imageCount %d: main.dol rejects this at 0x803EC800'
                             % self.count)
        if self.b16:
            comp_bytes, comp_count = self.b16, (self.bits >> 3) // self.b16
        else:
            comp_bytes, comp_count = self.bits >> 3, 1
        picked = choose_format(comp_bytes, comp_count, self.b19 == 1)
        if picked is None:
            raise ValueError('no format for %d bits' % self.bits)
        self.engine_fmt, self.fmt = picked
        self.faces = 6 if (self.b17 & 1) else 1
        self.paired = (self.engine_fmt == 9)      # CMPR colour + CMPR alpha
        self.levels = self.max_lod + 1
        one = chain_bytes(self.width, self.height, self.fmt, self.levels)
        self.chain_bytes = one
        self.payload = one * (2 if self.paired else 1) * self.faces
        self.data = blob[32:]

    def __repr__(self):
        return ('<Wit %dx%d %s lod=%d faces=%d%s>'
                % (self.width, self.height, GXNAME[self.fmt], self.max_lod,
                   self.faces, ' paired' if self.paired else ''))

    def chain_offset(self, face=0, half=0):
        """Byte offset of one mip chain. `half` 1 is the alpha chain."""
        per_face = self.chain_bytes * (2 if self.paired else 1)
        return face * per_face + half * self.chain_bytes

    def level_offset(self, level, face=0, half=0):
        off = self.chain_offset(face, half)
        w, h = self.width, self.height
        for _ in range(level):
            off += level_bytes(w, h, self.fmt)
            w, h = level_dims(w, h, 1)
        return off

    def level(self, level=0, face=0, half=0):
        """Raw tiled bytes of one level, with its dimensions."""
        w, h = level_dims(self.width, self.height, level)
        off = self.level_offset(level, face, half)
        return w, h, self.data[off:off + level_bytes(w, h, self.fmt)]


def read(path):
    with open(path, 'rb') as f:
        return Wit(f.read())
