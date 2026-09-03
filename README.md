# wittool — Wii texture tool for Star Wars Battlefront III

This tool reads and writes `.wit` files. A `.wit` file is one texture used by the
Wii (R9) version of Star Wars Battlefront III.

With it you can turn a `.wit` into a PNG, edit the PNG in any image editor, and
turn it back into a `.wit` that the game will load.

---

## 1. Before you start

**You need Python 3.** Nothing else. No pip install, no image library.

Check it works:

```bash
python tools/wii/wittool.py --help
```

**Where the textures live.** In an extracted copy of the game disc:

```
<game>/DATA/files/assets/bf/tex_wi_v2/
```

Two kinds of file are in there:

| Path | Example | What it is |
| :--- | :--- | :--- |
| Named | `misctex/hud/rep_atte_icon.wit` | Menu, HUD and effect textures. The name tells you what it is. |
| Numbered | `textures/7f40ed03.wit` | Model textures. The name is just an ID number. It does not mean anything. |

**Loose files work.** The `.pak` files next to the pools are empty. You do not
need to repack anything. Replace the file and the game reads it.

**Always keep a backup** of any file before you change it. There is no undo.

---

## 2. Your first mod, in four steps

Say you want to change the imperial officer's uniform.

**Step 1 — find out which texture the model uses.**

Model textures are numbered, so you cannot tell from the name. Ask the tool:

```bash
python tools/wii/wittool.py xref "<game>/DATA/files/assets/bf/ob_wi_v194/cutscene_models/officer/ob.war"
```

It prints something like:

```
ob+0x00C0  570d8703  textures/570d8703.wit   1024x1024  CMPR
ob+0x00C8  1efa428b  textures/1efa428b.wit   256x256    CMPR
ob+0x00D0  19129887  textures/19129887.wit   64x64      CMPR
```

**Step 2 — turn it into a PNG so you can look at it.**

```bash
python tools/wii/wittool.py decode "<game>/.../textures/570d8703.wit" officer.png
```

Open `officer.png`. That one is the uniform.

**Step 3 — edit `officer.png` in any image editor.**

Keep the same width and height. Save it as a PNG again.

**Step 4 — turn it back into a `.wit`.**

```bash
python tools/wii/wittool.py replace "<game>/.../textures/570d8703.wit" officer.png new.wit
```

Then copy `new.wit` over the original (after backing the original up).

Use `replace`, not `encode`. `replace` copies all the settings from the file you
are replacing, so your new file matches what the game expects. `encode` makes
you choose those settings yourself.

---

## 3. The commands

### `info` — look at a file

```bash
python tools/wii/wittool.py info FILE.wit [FILE.wit ...]
```

Prints size, format, how many mipmap levels, and where each level starts. It
also prints the exact `encode` options that would rebuild the same kind of file.

### `check` — is this file valid?

```bash
python tools/wii/wittool.py check FILE.wit
python tools/wii/wittool.py check SOME_FOLDER
```

Give it a file or a folder. It tells you whether the game would accept the file,
and explains any problem in plain words. Run this on anything you build before
you put it in the game.

Exit code is 1 if any file would be rejected, so you can use it in a script.

### `decode` — `.wit` to PNG

```bash
python tools/wii/wittool.py decode IN.wit OUT.png
python tools/wii/wittool.py decode IN.wit OUT.png --level 2
python tools/wii/wittool.py decode IN.wit OUT.png --face 3
python tools/wii/wittool.py decode IN.wit OUT.png --alpha
```

| Option | Meaning |
| :--- | :--- |
| `--level N` | Which mipmap level. `0` is the full-size one. Default `0`. |
| `--face N` | Which cube map face, `0` to `5`. Default `0`. |
| `--alpha` | Save the see-through mask on its own instead of the colour. |

By default the colour and the see-through mask are combined into one PNG with
transparency. That is normally what you want.

### `dump` — every level and face at once

```bash
python tools/wii/wittool.py dump IN.wit OUT_FOLDER
```

Writes one PNG per level, per face, per layer. Useful for seeing what is
actually inside a file.

### `encode` — PNG to `.wit`

```bash
python tools/wii/wittool.py encode IN.png OUT.wit
python tools/wii/wittool.py encode IN.png OUT.wit --mode rgba8
python tools/wii/wittool.py encode IN.png OUT.wit --mode cmpr --levels 1
```

| Option | Meaning |
| :--- | :--- |
| `--mode NAME` | Which format to use. Default `cmpra`. See section 4. |
| `--levels N` | How many mipmap levels. Default: as many as fit. |
| `--normal` | Mark the file as a normal map. Changes nothing in this version of the game. Only use it to match an original file exactly. |

### `replace` — rebuild a texture, keeping its settings

```bash
python tools/wii/wittool.py replace ORIGINAL.wit NEW.png OUT.wit
```

This is the command to use for modding. It reads the format, level count, cube
map flag and normal flag from `ORIGINAL.wit` and applies them to your PNG. You
do not have to know or type any of those.

If your PNG is a different size from the original, it still works, and the tool
says so.

### `cube` — build a cube map (sky boxes)

```bash
python tools/wii/wittool.py cube OUT.wit PX.png NX.png PY.png NY.png PZ.png NZ.png
```

The six PNGs must be in this order, and all the same size:

1. `+X` — right
2. `-X` — left
3. `+Y` — up
4. `-Y` — down
5. `+Z` — front
6. `-Z` — back

Takes `--mode` and `--levels` like `encode`. Default mode is `cmpr`.

### `xref` — which textures does a model use?

```bash
python tools/wii/wittool.py xref PATH/TO/ob.war
python tools/wii/wittool.py xref PATH/TO/MODEL_FOLDER
python tools/wii/wittool.py xref PATH/TO/ob.war --root "<game>/.../tex_wi_v2"
```

Model files store texture ID numbers, not names. This command reads the ID
numbers out of the model and tells you which files they are.

Use `--root` if your game is not in the default location.

**One warning.** Small ID numbers are listed separately and marked. A number
like `00000003` is just as likely to be an ordinary number inside the model as a
texture ID. Ignore those unless you have another reason to trust them.

### `find` — search a texture folder

```bash
python tools/wii/wittool.py find "<game>/.../tex_wi_v2"
python tools/wii/wittool.py find "<game>/.../tex_wi_v2" --size 1024x1024
python tools/wii/wittool.py find "<game>/.../tex_wi_v2" --format CMPR
python tools/wii/wittool.py find "<game>/.../tex_wi_v2" --cube
python tools/wii/wittool.py find "<game>/.../tex_wi_v2" --paired
python tools/wii/wittool.py find "<game>/.../tex_wi_v2" --rejected
```

| Option | Shows only |
| :--- | :--- |
| `--size WxH` | Textures of exactly that size |
| `--format NAME` | `CMPR`, `RGBA8`, `RGB565`, `I8`, `IA8` |
| `--cube` | Cube maps |
| `--paired` | Textures that have a separate see-through mask |
| `--rejected` | Files the game cannot load at all |

---

## 4. Choosing a format

A `.wit` can hold its pixels in one of several ways. This is the `--mode`
option. Pick based on what your texture needs.

| Mode | Use it for | Quality | Size of a 512x512 |
| :--- | :--- | :--- | ---: |
| `cmpra` | Anything with see-through parts | Compressed | 342 KB |
| `cmpr` | Solid textures, no see-through parts | Compressed | 171 KB |
| `rgba8` | Small textures where quality matters | Perfect | 1365 KB |
| `rgb565` | Solid textures, no compression blocks | Medium | 683 KB |
| `i8` | Grey only, no colour | Grey only | 341 KB |
| `ia8` | Grey plus see-through | Grey only | 683 KB |

**`cmpra` is the default and is what the game uses for almost everything.**

### Why `cmpra` exists

`cmpr` is a compressed format. It saves a lot of memory but it can only store
"fully solid" or "fully invisible" for each pixel. It cannot do half-transparent.

So when the game needs real transparency, it stores the texture **twice**: once
for the colour, and once again for the see-through mask, drawn in grey. The tool
calls this a "paired" texture. `cmpra` builds both halves for you.

You do not have to do anything special. Give the tool a PNG with transparency
and use `cmpra`.

### A detail that matters if you build your own

The game reads the mask from the **green** channel of the second half. The tool
writes grey (red, green and blue all the same), so green is correct
automatically. Only worry about this if you are writing your own encoder.

---

## 5. Rules you must follow

The tool checks all of these for you. `check` will explain any that you break.

### Never go above 1024 pixels

**This is the one that catches people out.** If a texture is wider or taller
than 1024, the game does not show an error. It quietly loads a small white
placeholder instead. Your surface goes blank and nothing is logged anywhere.

If a texture looks plain white in game, check its size first.

### Sizes that are not powers of two can only have one mipmap level

A power of two is 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024.

If your texture is, say, 384x240, it must have exactly one level. The tool does
this automatically when you do not pass `--levels`.

### `cmpr` and `cmpra` do not work at every size

Compressed formats work in blocks. At some sizes the block layout the file uses
and the layout the console's graphics chip expects do not line up, and the
texture comes out as garbage.

The rule: for `cmpr` and `cmpra`, each dimension should be a multiple of 8, or
smaller than 8.

If your size does not fit, use `--mode rgba8`. That is exactly what the game's
own artists did. Every odd-sized texture in the game (18x17, 33x16, 56x56,
400x200) is `rgba8`, never compressed.

### The file length must match the header

The game works out how much memory to reserve by reading the header, then reads
that many bytes. If the file is shorter, it reads past the end of its own
memory. The tool refuses to write a file where these disagree, so you cannot get
this wrong by accident.

---

## 6. Things that will not work

Some parts of the format cannot be used, because the game itself cannot read
them. These are not tool limits.

- **More than one image in a file.** The game rejects this outright. 33 files in
  the game carry it and none of them can be loaded, even by the game itself.
- **Textures above 1024.** Three files in the game are 2048 wide. The game
  replaces all three with a white placeholder. They have always been broken.
- **Making up new texture IDs.** The numbers in `textures/` are not calculated
  from anything. There is no way to work out the number for a new texture. You
  can replace existing textures, but you cannot add new numbered ones.

---

## 7. When something goes wrong

| What you see | What it usually means |
| :--- | :--- |
| Surface is plain white | Texture is bigger than 1024. Check with `info`. |
| Texture looks scrambled | `cmpr` at a size that is not a multiple of 8. Use `--mode rgba8`. |
| See-through parts are wrong | You used `cmpr` instead of `cmpra`. |
| Nothing changed in game | You edited the wrong copy of the game, or the wrong texture ID. Use `xref` again. |
| Tool says REFUSE | Read the message. It names the rule and the exact reason. |

**A note on crashes.** If the game shows a GPU error, that is usually the
emulator, not your texture. Dolphin's dual core mode can make the game's own
graphics watchdog fire when nothing is actually wrong. Try again with dual core
turned off before you assume your file is bad. Texture *content* cannot cause
this — the size and layout are what matter, and `check` verifies those.

---

## 8. The other files here

You do not need these to mod. They are the tool's parts, and the proof it is
correct.

| File | What it is |
| :--- | :--- |
| `wit.py` | The format itself: header, how the format is chosen, where each level sits. Every rule names the place in `main.dol` that proves it. |
| `witwrite.py` | Building a `.wit` from pixels. |
| `witpix.py` | Turning stored pixels back into an image. |
| `witcheck.py` | The rules from section 5, and the code in the game that enforces each one. |
| `witxref.py` | Reading texture IDs out of a model. |
| `png.py` | A small PNG reader and writer, so no image library is needed. |
| `witcorpus.py` | Tests. See below. |

### Running the tests

```bash
python tools/wii/witcorpus.py sizes       # predicts every file's length from its header
python tools/wii/witcorpus.py mips        # checks the pixel layout is read correctly
python tools/wii/witcorpus.py roundtrip   # decodes and re-encodes real textures
```

`mips` needs numpy. The others do not. `roundtrip` is slow, because the
compressor is plain Python.

Last full run: 10,280 of 10,317 files predicted exactly. Of the rest, 36 are
files the game itself refuses, and 1 ships with no pixels in it.
