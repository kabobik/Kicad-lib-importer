#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a minimal 24x24 plugin icon (icon.png)."""
import struct
import zlib
import os


def create_icon(path):
    """Create a 24x24 PNG with a 'G' letter on dark-blue background."""
    w, h = 24, 24
    rows = []
    for y in range(h):
        row = b'\x00'  # filter byte
        for x in range(w):
            # "G" shape
            is_g = (
                (2 <= y <= 5 and 6 <= x <= 18) or      # top bar
                (2 <= y <= 21 and 4 <= x <= 7) or       # left bar
                (18 <= y <= 21 and 6 <= x <= 18) or     # bottom bar
                (12 <= y <= 21 and 16 <= x <= 19) or    # right-bottom bar
                (11 <= y <= 14 and 12 <= x <= 19)       # middle-right bar
            )
            if is_g:
                row += b'\xff\xff\xff'  # white G
            else:
                row += b'\x1a\x47\x8a'  # dark blue background
        rows.append(row)
    raw = b''.join(rows)

    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', ihdr)
    png += chunk(b'IDAT', zlib.compress(raw))
    png += chunk(b'IEND', b'')

    with open(path, 'wb') as f:
        f.write(png)


if __name__ == '__main__':
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.png')
    create_icon(icon_path)
    print("icon.png created: {p}".format(p=icon_path))
