# Bug: ReadProperties() incorrectly strips trailing null byte from binary records, causing crash on Altium .SchLib import

## Summary

`ALTIUM_BINARY_PARSER::ReadProperties()` unconditionally strips a trailing `\0` byte from record data **before** checking the `isBinary` flag. For binary records (e.g., PinFrac compressed data), the trailing `0x00` is part of the zlib payload, not a string terminator. This causes `ALTIUM_COMPRESSED_READER::ReadCompressedString()` → `ReadFullPascalString()` to throw `std::out_of_range("ALTIUM_BINARY_READER: out of range")`, aborting the entire library import.

## KiCad Version

- **KiCad:** 9.0.7 (Ubuntu 24.04 PPA: `9.0.7~ubuntu24.04.1`)
- **Bug also present in:** `master` branch (verified via GitLab source)

## Steps to Reproduce

1. Obtain an Altium `.SchLib` file containing components whose PinFrac compressed records happen to end with a `0x00` byte (e.g., ATMega128, STM32F401CCU6, MAX7219).
2. Run: `kicad-cli sym upgrade file.SchLib -o output.kicad_sym --force`
3. Observe: `Unable to convert library` (exit code 2).

Alternatively, open the file via **Symbol Editor → File → Import → Non-KiCad Symbol Library** — same crash.

## Expected Behavior

The library should be imported successfully, converting all symbols to `.kicad_sym` format.

## Actual Behavior

Import fails silently. `ConvertLibrary()` catches the exception via `catch(...)` and returns `false`:

```
Unable to convert library
```

## Root Cause Analysis

File: `common/io/altium/altium_binary_parser.cpp`, `ReadProperties()` method.

```cpp
// Line 375:
bool hasNullByte = m_pos[length - 1] == '\0';

// Line 385: null byte is stripped BEFORE the isBinary check
std::string str = std::string( m_pos, length - ( hasNullByte ? 1 : 0 ) );
m_pos += length;

// Line 387: binary data is dispatched with already-truncated string
if( isBinary )
{
    return handleBinaryData( str );  // str is 1 byte too short!
}
```

The null-byte stripping logic is designed for text records (`|KEY=VALUE|...\0`), where the trailing `\0` is a string terminator. However, for binary records (flagged by MSB of the length field), the data contains raw compressed bytes. When the zlib stream happens to end with `0x00`, `ReadProperties()` incorrectly identifies it as a null terminator and truncates the data.

This truncation causes `ALTIUM_COMPRESSED_READER::ReadCompressedString()` to fail:
1. `ReadShortPascalString()` reads the pin index — OK
2. `ReadFullPascalString()` reads a 4-byte length field indicating N bytes of zlib data
3. Only N-1 bytes remain (due to truncation) → **throws `std::out_of_range`**

### Stack trace (obtained via GDB with `kicad-dbg` symbols):

```
#0  ALTIUM_BINARY_READER::ReadFullPascalString()        ← THROW (altium_binary_parser.h:401)
#1  ALTIUM_COMPRESSED_READER::ReadCompressedString()     (altium_binary_parser.h:432)
#2  operator() [parse_binary_pin_frac lambda]            (sch_io_altium.cpp:4598)
#3  std::function::operator()                            ← handleBinaryData callback
#4  ALTIUM_BINARY_PARSER::ReadProperties()               (altium_binary_parser.cpp:387)
#5  SCH_IO_ALTIUM::ParseLibFile()
#6  SCH_IO_ALTIUM::ensureLoadedLibrary()
#7  SCH_IO_ALTIUM::doEnumerateSymbolLib()
#8  SCH_IO_ALTIUM::EnumerateSymbolLib()
#9  SCH_IO_MGR::ConvertLibrary()
```

## Proposed Fix

For binary records, the trailing `\0` should **not** be stripped:

```diff
--- a/common/io/altium/altium_binary_parser.cpp
+++ b/common/io/altium/altium_binary_parser.cpp
@@ -382,7 +382,7 @@ std::map<wxString, wxString> ALTIUM_BINARY_PARSER::ReadProperties(
 
     // we use std::string because std::string can handle NULL-bytes
     // wxString would end the string at the first NULL-byte
-    std::string str = std::string( m_pos, length - ( hasNullByte ? 1 : 0 ) );
+    std::string str = std::string( m_pos, length - ( ( hasNullByte && !isBinary ) ? 1 : 0 ) );
     m_pos += length;
 
     if( isBinary )
```

This preserves the existing behavior for text records while ensuring binary records receive their full, unmodified payload.

## Verification

Using a test `.SchLib` file with 311 components, the following 10 PinFrac records in 9 components are affected by this bug:

| Component | PinFrac record # | Record length | zlib needs | zlib available (after truncation) |
|---|---|---|---|---|
| ATMega128 | 64 | 25 | 17 | 16 |
| ATtiny13 | 8 | 24 | 17 | 16 |
| CY8C29466-24SX | 3 | 27 | 20 | 19 |
| MAX7219 | 22 | 28 | 20 | 19 |
| PIC32MX795F512LT-80V_PT | 100 | 25 | 17 | 16 |
| STM32F303CCT6 | 1 | 27 | 20 | 19 |
| STM32F401CCU6 | 36, 45 | 28 | 20 | 19 |
| STP16CP05 | 17 | 28 | 20 | 19 |
| TPS61088RHLR | 4 | 27 | 20 | 19 |

All 10 records have zlib data ending with `0x00`. Without the truncation, all decompress successfully to valid 12-byte PinFrac structures (x_frac, y_frac, len_frac as int32).

## Test File

A minimal `.SchLib` file (`test_bug_nullbyte.SchLib`) is attached for reproduction. It contains a single ATtiny13 component whose PinFrac record #8 (pin index 7) has zlib-compressed data ending with `0x00`, triggering the bug.

```bash
kicad-cli sym upgrade test_bug_nullbyte.SchLib -o /tmp/out.kicad_sym --force
# Expected: successful conversion
# Actual: "Unable to convert library" (exit code 2)
```

## Environment

- **OS:** Ubuntu 24.04 LTS (x86_64)
- **KiCad:** 9.0.7 from PPA `ppa:kicad/kicad-9.0-releases`
- **Debug symbols:** `kicad-dbg` 9.0.7

## Additional Notes

- The `ConvertLibrary()` function in `sch_io_mgr.cpp` silences this exception with `catch(...)`, making it hard to diagnose without instrumentation.
- The same code path is triggered by `LoadSymbol()`, `EnumerateSymbolLib()`, and `ImportSymbol()` in the Symbol Editor.
- Any Altium `.SchLib` with PinFrac compressed records ending in `0x00` will trigger this bug. The probability depends on the zlib output — roughly ~1-3% of PinFrac records are affected in practice.
