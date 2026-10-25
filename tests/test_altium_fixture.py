"""Keep the Altium regression payload intact inside a valid CFB library."""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('fixture_writer', ROOT / 'repro/create_minimal_test.py')
WRITER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WRITER)


def read_streams(path):
    data = Path(path).read_bytes()
    sector_size = 1 << struct.unpack_from('<H', data, 30)[0]
    def sector(index):
        return data[(index + 1) * sector_size:(index + 2) * sector_size]
    fat = struct.unpack('<128I', sector(struct.unpack_from('<I', data, 76)[0]))
    def chain(start, table, get_block):
        result = b''
        seen = set()
        while start != 0xFFFFFFFE:
            if start in seen:
                raise ValueError('Cyclic sector chain')
            seen.add(start)
            result += get_block(start)
            start = table[start]
        return result
    directory = chain(struct.unpack_from('<I', data, 48)[0], fat, sector)
    entries = {}
    for offset in range(0, len(directory), 128):
        entry = directory[offset:offset + 128]
        if entry[66] == 0:
            continue
        name_len = struct.unpack_from('<H', entry, 64)[0]
        entries[entry[:name_len - 2].decode('utf-16-le')] = entry
    root_start, root_size = struct.unpack_from('<IQ', entries['Root Entry'], 116)
    mini_stream = chain(root_start, fat, sector)[:root_size]
    mini_fat = struct.unpack('<128I', chain(struct.unpack_from('<I', data, 60)[0], fat, sector))
    streams = {}
    for name, entry in entries.items():
        if entry[66] != 2:
            continue
        start, size = struct.unpack_from('<IQ', entry, 116)
        streams[name] = chain(start, mini_fat, lambda i: mini_stream[i * 64:(i + 1) * 64])[:size]
    return streams


def compressed_pin_records(stream):
    offset = 0
    while offset < len(stream):
        size = struct.unpack_from('<I', stream, offset)[0]
        record = stream[offset + 4:offset + 4 + (size & 0xFFFFFF)]
        offset += 4 + (size & 0xFFFFFF)
        if size & 0xFF000000:
            start = 2 + record[1]
            length = struct.unpack_from('<I', record, start)[0]
            yield record[start + 4:start + 4 + length]


class AltiumFixtureTests(unittest.TestCase):
    def test_header_and_original_regression_payloads(self):
        streams = read_streams(ROOT / 'fixtures/test_bug_nullbyte.SchLib')
        header = streams['FileHeader']
        self.assertEqual(struct.unpack_from('<I', header)[0], len(header) - 4)
        self.assertIn(b'Schematic Library Editor Binary File Version 5.0', header)
        expected = {
            'Data': '23dd969a821030020921c1eeaeb70fb87ca068f0329b4e7e2d71f423bd24831e',
            'PinFrac': 'd894bc9ed952303c5e1f1c63d66a81daf851adb2406521aa8ff085104f85e572',
        }
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256(streams[name]).hexdigest(), digest)
        compressed = list(compressed_pin_records(streams['PinFrac']))
        self.assertEqual(len(compressed), 8)
        self.assertEqual(compressed[-1][-1], 0)
        self.assertEqual(len(zlib.decompress(compressed[-1])), 12)
        with self.assertRaises(zlib.error):
            zlib.decompress(compressed[-1][:-1])

    def test_generator_preserves_payloads_and_emits_header(self):
        streams = read_streams(ROOT / 'fixtures/test_bug_nullbyte.SchLib')
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            output = Path(tmp) / 'minimal.SchLib'
            WRITER.create_minimal_schlib(streams['Data'], streams['PinFrac'], 'ATtiny13', output)
            self.assertEqual(read_streams(output), streams)

    def test_synthetic_binary_null_is_compressed_data_not_terminator(self):
        with contextlib.redirect_stdout(io.StringIO()):
            _, pinfrac = WRITER.create_synthetic_data()
        compressed = list(compressed_pin_records(pinfrac))
        self.assertEqual(compressed[-1][-1], 0)
        self.assertTrue(pinfrac.endswith(compressed[-1]))
        self.assertEqual(len(zlib.decompress(compressed[-1])), 12)


if __name__ == '__main__':
    unittest.main()
