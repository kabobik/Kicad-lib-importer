# GitLab Issue — Copy-Paste Guide
# ================================
# Каждая секция ниже = одно поле формы.
# Копируй содержимое каждой секции в соответствующее поле.


## ===== TITLE =====

ReadProperties() incorrectly strips trailing null byte from binary records, causing crash on Altium .SchLib import


## ===== DESCRIPTION =====
## (What is the current behavior and what is the expected behavior?)

### Current behavior

Importing an Altium `.SchLib` file fails silently when any PinFrac compressed record happens to end with a `0x00` byte.

`kicad-cli sym upgrade file.SchLib -o output.kicad_sym --force` prints `Unable to convert library` (exit code 2). The Symbol Editor import (File → Import Non-KiCad Symbol Library) shows the same error.

The root cause is in `ALTIUM_BINARY_PARSER::ReadProperties()` (`common/io/altium/altium_binary_parser.cpp`):

```cpp
// Line 375:
bool hasNullByte = m_pos[length - 1] == '\0';

// Line 385: null byte is stripped BEFORE the isBinary check
std::string str = std::string( m_pos, length - ( hasNullByte ? 1 : 0 ) );
m_pos += length;

if( isBinary )
{
    return handleBinaryData( str );  // str is 1 byte too short!
}
```

The null-byte stripping logic is designed for **text** records (`|KEY=VALUE|...\0`), where `\0` is a string terminator. For **binary** records (flagged by MSB of the length field), the data contains raw compressed bytes. When the zlib payload happens to end with `0x00`, it is misidentified as a null terminator and truncated. This causes `ALTIUM_COMPRESSED_READER::ReadCompressedString()` → `ReadFullPascalString()` to throw `std::out_of_range("ALTIUM_BINARY_READER: out of range")`.

Stack trace (obtained via GDB with `kicad-dbg` symbols):
```
#0  ALTIUM_BINARY_READER::ReadFullPascalString()         ← THROW (altium_binary_parser.h:401)
#1  ALTIUM_COMPRESSED_READER::ReadCompressedString()      (altium_binary_parser.h:432)
#2  operator() [parse_binary_pin_frac lambda]             (sch_io_altium.cpp:4598)
#3  std::function::operator()                             ← handleBinaryData callback
#4  ALTIUM_BINARY_PARSER::ReadProperties()                (altium_binary_parser.cpp:387)
#5  SCH_IO_ALTIUM::ParseLibFile()
#6  SCH_IO_ALTIUM::ensureLoadedLibrary()
#7  SCH_IO_ALTIUM::doEnumerateSymbolLib()
#8  SCH_IO_ALTIUM::EnumerateSymbolLib()
#9  SCH_IO_MGR::ConvertLibrary()
```

Note: `ConvertLibrary()` silences this exception with `catch(...)`, making it very hard to diagnose without instrumentation.

In practice, roughly 1–3% of PinFrac records have zlib output ending with `0x00`. A large 311-component library had 10 affected records across 9 components.

### Expected behavior

The library should be imported successfully. For binary records, the trailing `\0` is part of the zlib payload and must NOT be stripped.

### Proposed fix

One-line change:

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


## ===== STEPS TO REPRODUCE =====

1. Download the attached `Attiny-test.SchLib` file (6 KB, single ATtiny13 component created in Altium Designer).
2. Run: `kicad-cli sym upgrade Attiny-test.SchLib -o /tmp/out.kicad_sym --force`
3. Observe: `Unable to convert library` (exit code 2).

Alternatively: open Symbol Editor → File → Import Non-KiCad Symbol Library → select the file → same failure.

**Why this file triggers the bug:** The ATtiny13 component has 8 PinFrac compressed records. Record #8 (pin index 7) has a zlib payload that ends with `0x00`. `ReadProperties()` strips this byte, making `ReadFullPascalString()` throw `out_of_range` because the zlib length field says 17 bytes but only 16 remain.


## ===== KICAD VERSION =====

```
Application: kicad-cli x86_64 on x86_64

Version: 9.0.7-9.0.7~ubuntu24.04.1, release build

Libraries:
        wxWidgets 3.2.4
        FreeType 2.13.2
        HarfBuzz 8.3.0
        FontConfig 2.15.0
        libcurl/8.5.0 OpenSSL/3.0.13 zlib/1.3 brotli/1.1.0 zstd/1.5.5 libidn2/2.3.7 libpsl/0.21.2 (+libidn2/2.3.7) libssh/0.10.6/openssl/zlib nghttp2/1.59.0 librtmp/2.3 OpenLDAP/2.6.7

Platform: Linux Mint 22.2, 64 bit, Little endian, wxBase, cinnamon, x11

Build Info:
        Date: Jan  1 2026 22:15:57
        wxWidgets: 3.2.4 (wchar_t,wx containers) GTK+ 0.0
        Boost: 1.83.0
        OCC: 7.6.3
        Curl: 8.5.0
        ngspice: 42
        Compiler: GCC 13.3.0 with C++ ABI 1018
        KICAD_IPC_API=ON
```

Bug is also present in the `master` branch (verified via GitLab source inspection).


## ===== ATTACHMENTS =====
## (Drag & drop the file to the GitLab issue)

# File: Attiny-test.SchLib (6144 bytes)
# Location: /home/anton/VsCode/KiCAD_Importer/Attiny-test.SchLib
