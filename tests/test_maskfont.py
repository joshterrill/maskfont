import io
import os
import sys

import pytest
import uharfbuzz as hb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import maskfont  # noqa: E402

DONOR = "/System/Library/Fonts/Supplemental/Arial.ttf"


def test_chunk_balanced_and_order_preserving():
    assert maskfont.chunk_input("kitten", 3) == ["ki", "tt", "en"]


def test_chunk_distributes_remainder_to_front():
    # len 7 into 2 -> sizes 4,3
    assert maskfont.chunk_input("banana!", 2) == ["bana", "na!"]


def test_chunk_equal_length_is_one_per_slot():
    assert maskfont.chunk_input("abc", 3) == ["a", "b", "c"]


def test_chunk_rejects_output_longer_than_input():
    with pytest.raises(ValueError):
        maskfont.chunk_input("hi", 5)


def _visible_text(font_bytes, text):
    """Return what HarfBuzz actually draws for `text` with this font,
    i.e. the characters spelled by the post-GSUB glyph run."""
    face = hb.Face(font_bytes)
    font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"calt": True})
    order = maskfont.glyph_order_from_bytes(font_bytes)
    out = []
    for info in buf.glyph_infos:
        name = order[info.codepoint]  # codepoint == glyph id after shaping
        assert name.startswith("g_"), f"unexpanded glyph {name!r} leaked"
        out.append(chr(int(name[2:], 16)))
    return "".join(out)


@pytest.mark.parametrize(
    "inp,out",
    [
        ("kitten", "cat"),
        ("banana!", "aa"),  # repeated output char -> different chunks
        ("abcdef", "xyz"),
        ("hello world", "hi"),
        ("same", "same"),  # input == output length
        ("solo", "z"),  # single output codepoint
    ],
)
def test_display_shows_input(inp, out):
    fb = maskfont.build_font(inp, out, donor_path=DONOR, family_name="Mask")
    data = io.BytesIO()
    fb.save(data)
    assert _visible_text(data.getvalue(), out) == inp


def test_copied_text_is_output_in_demo_html():
    html = maskfont.demo_html("kitten", "cat", family_name="Mask", woff2_b64="AAAA")
    span = html.split('class="masked">', 1)[1].split("</p>", 1)[0]
    assert span == "cat"
