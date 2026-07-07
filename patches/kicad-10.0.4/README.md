# KiCad 10.0.4 patch series

`series` is the single source of patch application order.  Patch files are grouped into
topic directories only for navigation.

- `00-core/` - shared behavior and low-level fixes.
- `10-schematic/` - schematic editor interaction and drawing changes.
- `20-project-tree/` - project tree behavior.
- `30-lib-tree/` - library tree model, grouping, display, and compact mode.
- `40-symbol-sidebar/` - schematic symbol library sidebar UI.

Keep patch numbers global across all topic directories.  Do not restart numbering inside
each directory.
