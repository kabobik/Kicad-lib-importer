"""Run KiCad's actual cache getter across deterministic background replacement.

Extract the production getter and storage declarations from the cached 10.0.8
archive, then apply the complete series. The tiny C++ harness supplies only
FOOTPRINT storage and a writer; it does not reproduce the GUI or disk importer.
The unpatched getter must lose its object, while patched snapshots must retain
it through replacement, erase, and removal of the whole library.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "cache/sources/kicad-10.0.8.tar.gz"
SERIES = ROOT / "patches/kicad-10.0.8/series"
SOURCE = "pcbnew/footprint_library_adapter.cpp"
HEADER = "pcbnew/footprint_library_adapter.h"

PRELUDE = r'''
#include <atomic>
#include <cassert>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <thread>
#include <type_traits>
#include <vector>
using wxString = std::string;
template<typename T> struct LEAK_AT_EXIT {
    T value;
    T& Get() { return value; }
};
struct FOOTPRINT {
    static inline std::atomic<int> alive = 0;
    int value;
    explicit FOOTPRINT(int v) : value(v) { ++alive; }
    ~FOOTPRINT() { --alive; }
};
'''

MAIN = r'''
int main() {
    using Adapter = FOOTPRINT_LIBRARY_ADAPTER;
    Adapter adapter;
    assert(adapter.GetFootprints("missing").empty());
    for (int operation = 0; operation != 3; ++operation) {
        {
            std::unique_lock lock(Adapter::PreloadedFootprintsMutex);
            auto& entries = Adapter::PreloadedFootprints.Get()["lib"];
            entries.emplace_back(new FOOTPRINT(42));
        }
        auto snapshot = adapter.GetFootprints("lib");
        auto secondReader = snapshot;
        assert(snapshot.size() == 1);
        assert(snapshot[0]->value == 42);

        std::thread loader([&] {
            std::unique_lock lock(Adapter::PreloadedFootprintsMutex);
            auto& cache = Adapter::PreloadedFootprints.Get();
            if (operation == 0) {
                auto& entries = cache["lib"];
                // Match enumerateLibrary(): move-assign a replacement cache vector.
                std::remove_reference_t<decltype(entries)> replacement;
                replacement.emplace_back(new FOOTPRINT(99));
                entries = std::move(replacement);
            } else if (operation == 1) {
                cache["lib"].erase(cache["lib"].begin());
            } else {
                cache.erase("lib");
            }
        });
        loader.join();
        const int cachedObjects = operation == 0 ? 1 : 0;
        // Detect the baseline dangling pointer without actually dereferencing freed memory.
        if (FOOTPRINT::alive == cachedObjects) {
            std::cout << "snapshot object was destroyed by loader\n";
            return 77;
        }
        assert(FOOTPRINT::alive == cachedObjects + 1);
        assert(snapshot[0]->value == 42);
        auto current = adapter.GetFootprints("lib");
        assert(current.size() == static_cast<size_t>(cachedObjects));
        if (cachedObjects) assert(current[0]->value == 99);
        snapshot.clear();
        assert(FOOTPRINT::alive == cachedObjects + 1);
        secondReader.clear();
        assert(FOOTPRINT::alive == cachedObjects);
        current.clear();
        {
            std::unique_lock lock(Adapter::PreloadedFootprintsMutex);
            Adapter::PreloadedFootprints.Get().clear();
        }
        assert(FOOTPRINT::alive == 0);
    }
    std::cout << "snapshots survive replace, erase and library removal; no leaked objects\n";
}
'''


def harness(source, header):
    signature = re.search(r"^std::vector<.*> FOOTPRINT_LIBRARY_ADAPTER::GetFootprints\([^\n]+", source, re.M)
    start = signature.start()
    end = source.index("\n}\n", start) + 3
    method = source[start:end]
    declaration = re.search(r"^    std::vector<.*> GetFootprints\([^\n]+", header, re.M).group()
    storage = re.search(r"^    static LEAK_AT_EXIT<[^\n]+ PreloadedFootprints;", header, re.M).group()
    definition = re.search(r"^LEAK_AT_EXIT<[^\n]+ FOOTPRINT_LIBRARY_ADAPTER::PreloadedFootprints;", source, re.M).group()
    return (PRELUDE + "class FOOTPRINT_LIBRARY_ADAPTER { public:\n" + declaration + "\n" + storage
            + "\nstatic std::shared_mutex PreloadedFootprintsMutex;\n};\n" + definition
            + "\nstd::shared_mutex FOOTPRINT_LIBRARY_ADAPTER::PreloadedFootprintsMutex;\n"
            + method + MAIN)


class FootprintSnapshotTests(unittest.TestCase):
    def run_binary(self, name):
        # LeakSanitizer cannot inspect threads in restricted/ptraced environments.
        # The harness explicitly counts live objects; ASan and UBSan remain enabled.
        env = {**os.environ,
               "ASAN_OPTIONS": os.environ.get("ASAN_OPTIONS", "") + ":detect_leaks=0"}
        return subprocess.run([str(self.binaries[name])], capture_output=True, text=True,
                              timeout=20, env=env)

    @classmethod
    def setUpClass(cls):
        if not ARCHIVE.exists() or any(not shutil.which(t) for t in ("c++", "patch")):
            raise unittest.SkipTest("Requires cached KiCad 10.0.8 source, c++ and patch")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        patches = [(SERIES.parent / line).resolve() for line in SERIES.read_text().splitlines()
                   if line and not line.startswith("#")]
        paths = {path for patch in patches
                 for path in re.findall(r"^--- a/(.+)$", patch.read_text(), re.M)}
        with tarfile.open(ARCHIVE) as archive:
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    member = archive.getmember("kicad-10.0.8/" + path)
                except KeyError:
                    continue  # Created by an earlier patch in the series.
                target.write_bytes(archive.extractfile(member).read())
        original = harness((root / SOURCE).read_text(), (root / HEADER).read_text())
        for patch in patches:
            subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(patch)],
                           cwd=root, check=True, capture_output=True)
        patched = harness((root / SOURCE).read_text(), (root / HEADER).read_text())
        cls.binaries = {}
        for name, cpp in (("original", original), ("patched", patched)):
            source = root / (name + ".cpp")
            source.write_text(cpp)
            binary = root / name
            subprocess.run(["c++", "-std=c++20", "-O1", "-g", "-pthread",
                            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                            str(source), "-o", str(binary)], check=True, capture_output=True)
            cls.binaries[name] = binary

    def test_original_getter_returns_dangling_snapshot(self):
        result = self.run_binary("original")
        self.assertEqual(result.returncode, 77, result.stdout + result.stderr)
        self.assertIn("destroyed by loader", result.stdout)

    def test_patched_snapshot_survives_cache_mutations(self):
        result = self.run_binary("patched")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no leaked objects", result.stdout)


if __name__ == "__main__":
    unittest.main()
