"""Exercise KiCad's actual splitter without building the full GUI.

Requires c++, wx-config, and the installer-cached source archives.
Only the two production method bodies are extracted; the harness supplies
their storage/accessors. Full annotation integration remains a GUI/QA check.
"""
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/kicad-10.0.7/0020-annotation-utf8-reference.patch"

HARNESS = r'''
#include <wx/string.h>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <string>
class SCH_REFERENCE
{
public:
    std::string m_ref;
    int m_numRef = -1;
    wxString m_numRefStr;
    bool m_isNew = false;
    const char* GetRefStr() const { return m_ref.c_str(); }
    void SetRefStr(const std::string& ref) { m_ref = ref; }
    void Split();
    bool IsSplitNeeded();
};
'''
MAIN = r'''
int main(int argc, char** argv)
{
    if (argc != 2) return 2;
    SCH_REFERENCE ref;
    ref.SetRefStr(argv[1]);
    const bool needed = ref.IsSplitNeeded();
    ref.Split();
    std::cout << ref.GetRefStr() << '\t' << ref.m_numRef << '\t'
              << ref.m_numRefStr.ToStdString() << '\t'
              << needed << '\t' << ref.IsSplitNeeded() << '\n';
}
'''


class ReferenceSplitTests(unittest.TestCase):
    version = "10.0.7"

    @classmethod
    def setUpClass(cls):
        source_archive = ROOT / f"cache/sources/kicad-{cls.version}.tar.gz"
        if not source_archive.exists() or any(not shutil.which(tool)
                                       for tool in ("c++", "wx-config", "patch")):
            raise unittest.SkipTest("Requires cached KiCad source, c++, wx-config and patch")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        paths = ("eeschema/sch_reference_list.cpp",
                 "qa/tests/eeschema/test_sch_reference_list.cpp")
        with tarfile.open(source_archive) as archive:
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(f"kicad-{cls.version}/" + path).read())
        source_path = root / paths[0]
        original = source_path.read_text()
        subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(PATCH)],
                       cwd=root, check=True, capture_output=True)
        patched = source_path.read_text()
        flags = shlex.split(subprocess.check_output(
            ["wx-config", "--cxxflags", "--libs", "base"], text=True))
        cls.binaries = {}
        for name, source, char_flag in (("original", original, "-fsigned-char"),
                                        ("signed", patched, "-fsigned-char"),
                                        ("unsigned", patched, "-funsigned-char")):
            start = source.index("void SCH_REFERENCE::Split()")
            end = source.index("wxString SCH_REFERENCE_LIST::Shorthand", start)
            cpp = root / (name + ".cpp")
            cpp.write_text(HARNESS + source[start:end] + MAIN)
            binary = root / name
            subprocess.run(["c++", "-std=c++17", char_flag, str(cpp), "-o", str(binary),
                            *flags], check=True, capture_output=True)
            cls.binaries[name] = binary

    def split(self, binary, reference):
        result = subprocess.run([str(self.binaries[binary]), reference],
                                check=True, capture_output=True, text=True)
        return result.stdout.rstrip("\n").split("\t")

    def test_original_reproduces_cyrillic_growth(self):
        reference = "С1"
        for _ in range(5):
            prefix, number, _, _, _ = self.split("original", reference)
            self.assertEqual(prefix, reference)
            self.assertEqual(number, "-1")
            reference = prefix + "1"
        self.assertEqual(reference, "С111111")

    def test_fixed_split_and_repeated_number_assignment(self):
        for binary in ("signed", "unsigned"):
            for prefix in ("C", "С", "ДД", "Ω", "電", "RС", "#PWR", "U2A"):
                with self.subTest(binary=binary, prefix=prefix):
                    self.assertEqual(self.split(binary, prefix + "001"),
                                     [prefix, "1", "001", "1", "0"])
                    self.assertEqual(self.split(binary, prefix + "?"),
                                     [prefix, "-1", "", "1", "0"])
                    self.assertEqual(self.split(binary, prefix),
                                     [prefix, "-1", "", "0", "0"])
                    reference = prefix + "1"
                    for _ in range(10):
                        actual_prefix, number, _, _, _ = self.split(binary, reference)
                        self.assertEqual(actual_prefix, prefix)
                        self.assertEqual(number, "1")
                        reference = actual_prefix + "1"
                    self.assertEqual(reference, prefix + "1")


class ReferenceSplit1008Tests(ReferenceSplitTests):
    version = "10.0.8"


if __name__ == "__main__":
    unittest.main()
