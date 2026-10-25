#!/usr/bin/env python3
"""
Create a minimal Altium .SchLib file that reproduces the KiCad bug:
ReadProperties() incorrectly strips trailing null byte from binary PinFrac records.

The bug occurs when compressed PinFrac data happens to end with 0x00,
which ReadProperties() mistakes for a string null terminator and strips,
causing ReadFullPascalString() to throw std::out_of_range.

This script extracts ATtiny13 from IC.SchLib and creates a minimal
single-component .SchLib for testing. It can also create a fully
synthetic test file without needing IC.SchLib.

Usage:
    python3 create_minimal_test.py [IC.SchLib]

If IC.SchLib is provided, extracts ATtiny13 from it.
Otherwise, creates a synthetic component with crafted PinFrac data.
"""

import struct
import sys
import os

# ── CFB constants ──
SECTOR_SIZE = 512
MINI_SECTOR_SIZE = 64
MINI_STREAM_CUTOFF = 4096
DIR_ENTRY_SIZE = 128
NOSTREAM = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD
CFB_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'


def encode_utf16(name):
    """Encode name to UTF-16LE, padded to 64 bytes."""
    encoded = name.encode('utf-16-le') + b'\x00\x00'  # null terminator
    byte_len = len(encoded)
    return encoded.ljust(64, b'\x00'), byte_len


def make_dir_entry(name, obj_type, color=1, left=NOSTREAM, right=NOSTREAM,
                   child=NOSTREAM, start=0, size=0):
    """Create a 128-byte directory entry."""
    name_bytes, name_len = encode_utf16(name)
    entry = bytearray(128)
    entry[0:64] = name_bytes
    struct.pack_into('<H', entry, 64, name_len)        # name size in bytes
    entry[66] = obj_type                                 # type
    entry[67] = color                                    # color (1=black)
    struct.pack_into('<I', entry, 68, left)              # left sibling
    struct.pack_into('<I', entry, 72, right)             # right sibling
    struct.pack_into('<I', entry, 76, child)             # child
    # CLSID (16 bytes at 80) = 0
    # State bits (4 bytes at 96) = 0
    # Timestamps (16 bytes at 100) = 0
    struct.pack_into('<I', entry, 116, start)            # start sector
    struct.pack_into('<I', entry, 120, size)             # size (low 32)
    struct.pack_into('<I', entry, 124, 0)                # size (high 32)
    return bytes(entry)


def pad_to(data, boundary):
    """Pad data to next boundary."""
    remainder = len(data) % boundary
    if remainder:
        data += b'\x00' * (boundary - remainder)
    return data


def create_minimal_schlib(data_stream, pinfrac_stream, component_name, output_path):
    """Write a CFB v3 library, including the required Altium FileHeader.

    Data and PinFrac are preserved verbatim so the binary null-byte regression
    reaches ReadProperties instead of failing earlier in ParseLibHeader.
    This small fixture writer supports streams below the 4096-byte cutoff.
    """
    properties = (
        b"|HEADER=Protel for Windows - Schematic Library Editor Binary File Version 5.0"
        b"|Weight=1|MinorVersion=9|UniqueID=TEST0001|\x00"
    )
    file_header = struct.pack('<I', len(properties)) + properties
    streams = [data_stream, pinfrac_stream, file_header]
    if any(not stream or len(stream) >= MINI_STREAM_CUTOFF for stream in streams):
        raise ValueError("Fixture streams must be nonempty and smaller than 4096 bytes")

    mini_stream = bytearray()
    mini_fat_entries = []
    starts = []
    for stream in streams:
        start = len(mini_fat_entries)
        starts.append(start)
        count = (len(stream) + MINI_SECTOR_SIZE - 1) // MINI_SECTOR_SIZE
        mini_stream += pad_to(stream, MINI_SECTOR_SIZE)
        mini_fat_entries.extend(range(start + 1, start + count))
        mini_fat_entries.append(ENDOFCHAIN)
    if len(mini_fat_entries) > SECTOR_SIZE // 4:
        raise ValueError("Fixture exceeds one mini-FAT sector")
    mini_fat_entries += [FREESECT] * (SECTOR_SIZE // 4 - len(mini_fat_entries))
    mini_fat = struct.pack('<128I', *mini_fat_entries)

    # FAT=0, directory=1->2, mini-FAT=3, root mini-stream=4->...
    root_start = 4
    root_data = pad_to(bytes(mini_stream), SECTOR_SIZE)
    root_sectors = len(root_data) // SECTOR_SIZE
    fat_entries = [FATSECT, 2, ENDOFCHAIN, ENDOFCHAIN]
    fat_entries += list(range(root_start + 1, root_start + root_sectors)) + [ENDOFCHAIN]
    fat_entries += [FREESECT] * (SECTOR_SIZE // 4 - len(fat_entries))
    fat = struct.pack('<128I', *fat_entries)

    # CFB orders sibling names by length, then case-insensitively.
    header_before_component = (len("FileHeader"), "FILEHEADER") < (
        len(component_name), component_name.upper())
    directory = make_dir_entry("Root Entry", 5, child=1,
                               start=root_start, size=len(mini_stream))
    directory += make_dir_entry(component_name, 1, child=2,
                                left=4 if header_before_component else NOSTREAM,
                                right=NOSTREAM if header_before_component else 4)
    directory += make_dir_entry("Data", 2, right=3, start=starts[0], size=len(data_stream))
    directory += make_dir_entry("PinFrac", 2, color=0, start=starts[1], size=len(pinfrac_stream))
    directory += make_dir_entry("FileHeader", 2, color=0, start=starts[2], size=len(file_header))
    directory = pad_to(directory, SECTOR_SIZE)

    header = bytearray(SECTOR_SIZE)
    header[:8] = CFB_MAGIC
    for offset, value in ((24, 0x003E), (26, 3), (28, 0xFFFE), (30, 9), (32, 6)):
        struct.pack_into('<H', header, offset, value)
    for offset, value in ((44, 1), (48, 1), (56, MINI_STREAM_CUTOFF),
                          (60, 3), (64, 1), (68, ENDOFCHAIN), (76, 0)):
        struct.pack_into('<I', header, offset, value)
    for index in range(1, 109):
        struct.pack_into('<I', header, 76 + index * 4, FREESECT)

    with open(output_path, 'wb') as output:
        output.write(header + fat + directory + mini_fat + root_data)
    print(f"Created {output_path}: {component_name}, Data={len(data_stream)}, PinFrac={len(pinfrac_stream)}")


def create_synthetic_data():
    """
    Create synthetic but valid Data and PinFrac streams that trigger the bug.
    No dependency on IC.SchLib.
    """
    import zlib

    # ── Data stream: COMPONENT record + 2 PIN records ──
    data = bytearray()

    # Record 0: COMPONENT (text format)
    comp_props = (
        "|RECORD=1"
        "|LibReference=TestComp"
        "|PartCount=2"
        "|DisplayModeCount=1"
        "|IndexInSheet=-1"
        "|OwnerPartId=-1"
        "|CurrentPartId=1"
        "|LibraryPath=*"
        "|SourceLibraryName=test.SchLib"
        "|TargetFileName=*"
        "|Description=Test component for bug reproduction"
        "|ComponentDescription=Test"
        "|"
    )
    comp_bytes = comp_props.encode('latin-1') + b'\x00'
    data += struct.pack('<I', len(comp_bytes))  # length, no binary flag
    data += comp_bytes

    # Records 1-2: PIN records (binary format)
    for pin_idx in range(2):
        pin_data = bytearray()
        pin_data += struct.pack('<i', 2)           # RECORD=2 (PIN)
        pin_data += struct.pack('B', 0)            # unknown
        pin_data += struct.pack('<h', 1)           # ownerPartId
        pin_data += struct.pack('B', 0)            # displayMode
        pin_data += struct.pack('B', 0)            # innerEdge
        pin_data += struct.pack('B', 0)            # outerEdge
        pin_data += struct.pack('B', 0)            # inner
        pin_data += struct.pack('B', 0)            # outer
        # TEXT (ShortPascalString)
        text = f"P{pin_idx+1}".encode('latin-1')
        pin_data += struct.pack('B', len(text)) + text
        pin_data += struct.pack('B', 0)            # unknown
        pin_data += struct.pack('B', 1)            # electrical (passive)
        pin_data += struct.pack('B', 0x11)         # pinConglomerate
        pin_data += struct.pack('<h', 20)          # pinLength
        pin_data += struct.pack('<h', -30 if pin_idx == 0 else 30)  # locationX
        pin_data += struct.pack('<h', 0)           # locationY
        pin_data += struct.pack('<i', 0)           # color
        # NAME (ShortPascalString)
        name = f"PIN{pin_idx+1}".encode('latin-1')
        pin_data += struct.pack('B', len(name)) + name
        # DESIGNATOR (ShortPascalString)
        des = f"{pin_idx+1}".encode('latin-1')
        pin_data += struct.pack('B', len(des)) + des
        # SWAPIDGROUP (ShortPascalString)
        pin_data += struct.pack('B', 0)
        # partSeq (ShortPascalString) — format: "part|&|seq"
        seq = f"1|&|0".encode('latin-1')
        pin_data += struct.pack('B', len(seq)) + seq

        pin_bytes = bytes(pin_data) + b'\x00'
        # Set binary flag (MSB of length)
        data += struct.pack('<I', len(pin_bytes) | 0x01000000)
        data += pin_bytes

    # ── PinFrac stream ──
    pinfrac = bytearray()

    # Record 0: Header (text format)
    hdr = "|HEADER=PinFrac|Weight=2|"
    hdr_bytes = hdr.encode('latin-1') + b'\x00'
    pinfrac += struct.pack('<I', len(hdr_bytes))
    pinfrac += hdr_bytes

    # Records 1-2: PinFrac entries (binary, compressed)
    for pin_idx in range(2):
        frac_data = struct.pack('<iii', 0, 0, 68504)  # x_frac, y_frac, len_frac

        if pin_idx == 1:
            # CRAFT the zlib data to end with 0x00 — this triggers the bug!
            # We need zlib.compress(frac_data) to end with 0x00.
            # If it doesn't naturally, we pad the input slightly.
            # Actually, let's just find input that compresses to end with 0x00.
            compressed = zlib.compress(frac_data)
            if compressed[-1] != 0x00:
                # Try different y_frac values until we get zlib ending with 0x00
                for y in range(-100000, 100000):
                    test_data = struct.pack('<iii', 0, y, 68504)
                    c = zlib.compress(test_data)
                    if c[-1] == 0x00:
                        frac_data = test_data
                        compressed = c
                        print(f"  Found y_frac={y} that produces zlib ending with 0x00")
                        break
                else:
                    # Fallback: try different compression levels
                    for level in range(1, 10):
                        c = zlib.compress(frac_data, level)
                        if c[-1] == 0x00:
                            compressed = c
                            print(f"  Found compression level {level} ending with 0x00")
                            break
        else:
            compressed = zlib.compress(frac_data)

        # Build compressed record: 0xD0 + ShortPascalString(pin_idx) + FullPascalString(zlib)
        rec = bytearray()
        rec += b'\xd0'
        idx_str = str(pin_idx).encode('ascii')
        rec += struct.pack('B', len(idx_str)) + idx_str
        rec += struct.pack('<I', len(compressed)) + compressed

        # Binary records have no string terminator: the final 0x00 belongs to zlib.
        rec_bytes = bytes(rec)
        pinfrac += struct.pack('<I', len(rec_bytes) | 0x01000000)
        pinfrac += rec_bytes

    print(f"  Last PinFrac record ends with: 0x{pinfrac[-2]:02x} 0x{pinfrac[-1]:02x}")

    return bytes(data), bytes(pinfrac)


def extract_from_schlib(schlib_path):
    """Extract ATtiny13 Data and PinFrac from IC.SchLib."""
    import olefile
    ole = olefile.OleFileIO(schlib_path)
    data = ole.openstream(['ATtiny13', 'Data']).read()
    pinfrac = ole.openstream(['ATtiny13', 'PinFrac']).read()
    ole.close()
    return data, pinfrac


def main():
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'test_bug_nullbyte.SchLib')

    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        print(f"Extracting ATtiny13 from {sys.argv[1]}...")
        data_stream, pinfrac_stream = extract_from_schlib(sys.argv[1])
        component_name = "ATtiny13"
    else:
        print("Creating synthetic test component...")
        data_stream, pinfrac_stream = create_synthetic_data()
        component_name = "TestComp"

    create_minimal_schlib(data_stream, pinfrac_stream, component_name, output_path)

    # Verify the file is readable
    try:
        import olefile
        ole = olefile.OleFileIO(output_path)
        entries = ole.listdir()
        print(f"\nVerification (olefile):")
        for e in entries:
            stream = ole.openstream(e) if ole.get_type(e) != 1 else None
            size = len(stream.read()) if stream else 0
            print(f"  {'/'.join(e)}: {size} bytes")
        ole.close()
        print("OK — file is valid OLE")
    except Exception as e:
        print(f"WARNING: olefile verification failed: {e}")

    print(f"\nTo reproduce the bug:")
    print(f"  kicad-cli sym upgrade {output_path} -o /tmp/test_output.kicad_sym --force")


if __name__ == '__main__':
    main()
