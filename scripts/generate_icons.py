#!/usr/bin/env python3
"""
Generates the two PWA icons (app/static/icons/icon-192.png, icon-512.png) —
a plain green square (matching app.css's theme colour, #0a5) with a white
"H" for Household. No image library needed: raw pixels, hand-built PNG
chunks (IHDR/IDAT/IEND), zlib for the DEFLATE compression PNG requires.

Safe to re-run: always overwrites both files deterministically from the
same drawing code, no randomness, no external input.

A successful run prints the two output paths and exits 0.
"""
import os
import struct
import sys
import zlib

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "static", "icons")

BG = (0x00, 0xAA, 0x55)   # #0a5 expanded — matches app.css's button/accent green
FG = (0xFF, 0xFF, 0xFF)   # white "H"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def _draw_h(size: int) -> list[list[tuple[int, int, int]]]:
    """A simple white 'H' on a green square, hand-rasterised. Margins and
    stroke width scale with the icon size so both 192px and 512px look the
    same shape, just sharper at the larger size."""
    pixels = [[BG for _ in range(size)] for _ in range(size)]
    margin = round(size * 0.28)
    stroke = max(2, round(size * 0.11))
    top, bottom = margin, size - margin
    left, right = margin, size - margin
    mid = size // 2

    for y in range(top, bottom):
        for x in range(left, left + stroke):       # left vertical bar
            pixels[y][x] = FG
        for x in range(right - stroke, right):      # right vertical bar
            pixels[y][x] = FG
    for y in range(mid - stroke // 2, mid + stroke // 2):
        for x in range(left, right):                 # crossbar
            pixels[y][x] = FG
    return pixels


def _encode_png(pixels: list[list[tuple[int, int, int]]]) -> bytes:
    size = len(pixels)
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type 0 (none) for every scanline
        for (r, g, b) in row:
            raw += bytes((r, g, b))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    idat = zlib.compress(bytes(raw), 9)

    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for size in (192, 512):
        path = os.path.join(OUT_DIR, f"icon-{size}.png")
        with open(path, "wb") as f:
            f.write(_encode_png(_draw_h(size)))
        print(f"Wrote {os.path.relpath(path)}")


if __name__ == "__main__":
    main()
