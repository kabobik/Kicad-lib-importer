# KiCad 10.0.5 patch series

This version reuses patch-release-compatible files from `kicad-10.0.4` and
keeps version-specific ports of `0008` and `0010` locally. The `series` file is
the single source of application order.

Patch `0001-gost-font-interline.patch` is intentionally omitted: KiCad 10.0.5
changed `OUTLINE_FONT::GetInterline()` upstream and no longer contains the
integer-division code fixed by that patch.

Patches `0008` and `0010` differ from their 10.0.4 counterparts only in context
changed by upstream. Their resulting local behavior remains the same.

The complete Release build and staged install were verified on CachyOS/Arch
with GCC 16.1.1. The resulting `kicad-cli` reports version `10.0.5`.

Validate the complete series on a clean source archive:

```bash
# Arch Linux
./scripts/build_and_install_arch.sh --version 10.0.5 --check

# Debian / Ubuntu
./scripts/build_and_install_ubuntu.sh --version 10.0.5 --check
```
