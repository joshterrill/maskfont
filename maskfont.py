from __future__ import annotations

import argparse
import base64
import io
import os

from fontTools.fontBuilder import FontBuilder
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

DEFAULT_DONOR = "/System/Library/Fonts/Supplemental/Arial.ttf"


def chunk_input(text: str, n: int) -> list[str]:
    """Split `text` into `n` ordered, length-balanced chunks.

    Extra characters go to the earliest chunks. Requires len(text) >= n so
    every chunk holds at least one character.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    if len(text) < n:
        raise ValueError(f"input length {len(text)} must be >= output length {n}")
    base, extra = divmod(len(text), n)
    chunks, i = [], 0
    for idx in range(n):
        size = base + (1 if idx < extra else 0)
        chunks.append(text[i : i + size])
        i += size
    return chunks


# glyph-name helpers (hex keeps names unique and valid fea identifiers)
def _gin(ch: str) -> str:  # input letter glyph
    return "g_%04X" % ord(ch)


def _gout(ch: str) -> str:  # output base glyph (cmap target, empty outline)
    return "out_%04X" % ord(ch)


def _gpos(i: int) -> str:  # per-position tag glyph (intermediate, empty)
    return "pos_%d" % i


def _open_donor(path: str) -> TTFont:
    if path.lower().endswith(".ttc"):
        return TTFont(path, fontNumber=0)
    return TTFont(path)


def build_font(
    input_text: str,
    output_text: str,
    donor_path: str = DEFAULT_DONOR,
    family_name: str = "Masked",
) -> FontBuilder:
    """Build and return a FontBuilder for the (input, output) pair."""
    if not output_text:
        raise ValueError("output text must not be empty")
    chunks = chunk_input(input_text, len(output_text))  # validates length

    donor = _open_donor(donor_path)
    dcmap = donor.getBestCmap()
    gset = donor.getGlyphSet()
    dhmtx = donor["hmtx"]
    upm = donor["head"].unitsPerEm

    distinct_in = sorted(set(input_text))
    missing = [c for c in distinct_in if ord(c) not in dcmap]
    if missing:
        raise ValueError(
            "donor font lacks glyphs for: "
            + ", ".join(f"{c!r} (U+{ord(c):04X})" for c in missing)
        )

    glyphs: dict[str, object] = {}
    metrics: dict[str, tuple[int, int]] = {}
    order = [".notdef"]

    pen = TTGlyphPen(None)
    glyphs[".notdef"] = pen.glyph()
    metrics[".notdef"] = (upm // 2, 0)

    for ch in distinct_in:
        dname = dcmap[ord(ch)]
        rec = DecomposingRecordingPen(gset)
        gset[dname].draw(rec)
        pen = TTGlyphPen(None)
        rec.replay(pen)
        name = _gin(ch)
        glyphs[name] = pen.glyph()
        metrics[name] = (dhmtx[dname][0], dhmtx[dname][1])
        order.append(name)

    for ch in sorted(set(output_text)):
        name = _gout(ch)
        glyphs[name] = TTGlyphPen(None).glyph()
        metrics[name] = (0, 0)
        order.append(name)
    for i in range(len(output_text)):
        name = _gpos(i)
        glyphs[name] = TTGlyphPen(None).glyph()
        metrics[name] = (0, 0)
        order.append(name)

    fb = FontBuilder(upm, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({ord(ch): _gout(ch) for ch in set(output_text)})
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    asc = getattr(donor["hhea"], "ascent", int(upm * 0.8))
    desc = getattr(donor["hhea"], "descent", -int(upm * 0.2))
    fb.setupHorizontalHeader(ascent=asc, descent=desc)
    fb.setupNameTable(
        {
            "familyName": family_name,
            "styleName": "Regular",
            "psName": family_name.replace(" ", "") + "-Regular",
        }
    )
    fb.setupOS2(
        sTypoAscender=asc, sTypoDescender=desc, usWinAscent=asc, usWinDescent=abs(desc)
    )
    fb.setupPost()

    addOpenTypeFeaturesFromString(fb.font, _feature_code(output_text, chunks))
    return fb


def _feature_code(output_text: str, chunks: list[str]) -> str:
    n = len(output_text)
    lines = [
        "languagesystem DFLT dflt;",
        "languagesystem latn dflt;",
        "",
        "feature calt {",
        "    lookup tag {",
    ]

    if n == 1:
        lines.append(f"        sub {_gout(output_text[0])}' by {_gpos(0)};")
    else:
        for i in range(n - 1, 0, -1):
            back = " ".join(_gpos(j) for j in range(i))
            lines.append(f"        sub {back} {_gout(output_text[i])}' by {_gpos(i)};")
        lines.append(
            f"        sub {_gout(output_text[0])}' "
            f"{_gout(output_text[1])} by {_gpos(0)};"
        )

    lines.append("    } tag;")

    multi = [(i, c) for i, c in enumerate(chunks) if len(c) > 1]
    single = [(i, c) for i, c in enumerate(chunks) if len(c) == 1]
    if multi:
        lines.append("    lookup expand_multi {")
        for i, c in multi:
            repl = " ".join(_gin(ch) for ch in c)
            lines.append(f"        sub {_gpos(i)} by {repl};")
        lines.append("    } expand_multi;")
    if single:
        lines.append("    lookup expand_single {")
        for i, c in single:
            lines.append(f"        sub {_gpos(i)} by {_gin(c)};")
        lines.append("    } expand_single;")

    lines.append("} calt;")
    return "\n".join(lines)


def glyph_order_from_bytes(font_bytes: bytes) -> list[str]:
    return TTFont(io.BytesIO(font_bytes)).getGlyphOrder()


def demo_html(
    input_text: str, output_text: str, family_name: str, woff2_b64: str
) -> str:
    esc = output_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html>
<meta charset="utf-8">
<title>maskfont demo</title>
<style>
  @font-face {{
    font-family: "{family_name}";
    src: url(data:font/woff2;base64,{woff2_b64}) format("woff2");
  }}
  body {{ font: 16px system-ui, sans-serif; max-width: 40rem;
         margin: 3rem auto; padding: 0 1rem; line-height: 1.5; }}
  .masked {{ font-family: "{family_name}"; font-size: 2rem; }}
  textarea {{ width: 100%; height: 4rem; font: 1rem monospace; }}
  code {{ background: #eee; padding: 0 .25rem; }}
</style>
<h1>maskfont demo</h1>
<p>The line below is rendered with the generated font. It <b>looks like</b>
the input string, but the characters underneath are the output string.</p>
<p class="masked">{esc}</p>
<p>Select that line, copy it, and paste it here to see what actually travels
on the clipboard:</p>
<textarea placeholder="paste here..."></textarea>
<p>Displayed (via glyphs): <code>{input_text}</code><br>
Copied (real characters): <code>{output_text}</code></p>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--input", required=True, help="text that is displayed (>= output length)"
    )
    ap.add_argument(
        "--output", required=True, help="text that is copied to the clipboard"
    )
    ap.add_argument("--name", default="Masked", help="font family name")
    ap.add_argument(
        "--donor", default=DEFAULT_DONOR, help="font to borrow letter outlines from"
    )
    ap.add_argument("--outdir", default=".", help="output directory")
    args = ap.parse_args(argv)

    fb = build_font(args.input, args.output, args.donor, args.name)
    os.makedirs(args.outdir, exist_ok=True)
    slug = args.name.replace(" ", "")

    ttf_path = os.path.join(args.outdir, slug + ".ttf")
    fb.save(ttf_path)

    buf = io.BytesIO()
    fb.font.flavor = "woff2"
    fb.font.save(buf)
    woff2 = buf.getvalue()
    woff2_path = os.path.join(args.outdir, slug + ".woff2")
    with open(woff2_path, "wb") as f:
        f.write(woff2)

    html = demo_html(
        args.input, args.output, args.name, base64.b64encode(woff2).decode("ascii")
    )
    html_path = os.path.join(args.outdir, slug + ".demo.html")
    with open(html_path, "w") as f:
        f.write(html)

    print(f"wrote {ttf_path}")
    print(f"wrote {woff2_path}")
    print(f"wrote {html_path}")
    print(f"  displayed: {args.input!r}")
    print(f"  copied:    {args.output!r}")


if __name__ == "__main__":
    main()
