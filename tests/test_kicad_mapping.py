import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kicad_mapping as km  # noqa: E402


class KicadMappingCliTests(unittest.TestCase):
    def test_parse_connection_string_preserves_driver_braces(self):
        parsed = km.parse_connection_string(
            "Driver={PostgreSQL Unicode};Server=db.example;Port=54320;"
            "Database=altium_components;Uid=kicad;Pwd=secret;SSLmode=require;"
        )

        self.assertEqual(parsed["driver"], "PostgreSQL Unicode")
        self.assertEqual(parsed["server"], "db.example")
        self.assertEqual(parsed["port"], "54320")
        self.assertEqual(parsed["database"], "altium_components")
        self.assertEqual(parsed["uid"], "kicad")
        self.assertEqual(parsed["pwd"], "secret")
        self.assertEqual(parsed["sslmode"], "require")

    def test_parse_id_list_accepts_ranges(self):
        self.assertEqual(km.parse_id_list("5,2,10-12,11"), [2, 5, 10, 11, 12])

    def test_filter_args_build_safe_where_clause(self):
        args = km.parse_args(
            [
                "filter",
                "-c",
                "Резисторы",
                "-t",
                "0603",
                "--filter",
                "manufacturer=vishay",
                "--exact",
                "reference=R",
                "--no-output",
            ]
        )

        where, params = km.build_where(args)

        self.assertIn('lt."ElementType" ILIKE %s', where)
        self.assertIn('l."Type" = %s', where)
        self.assertIn('l."Manufacturer" ILIKE %s', where)
        self.assertIn("l.reference_prefix = %s", where)
        self.assertEqual(params, ["%Резисторы%", "0603", "%vishay%", "R"])

    def test_apply_args_allow_designator_alias(self):
        args = km.parse_args(
            [
                "apply",
                "--ids",
                "1",
                "--designator",
                "R",
                "--set",
                "symbol=Device:R",
                "--dry-run",
            ]
        )

        library_updates, symbol, footprint = km.collect_updates(args)

        self.assertEqual(library_updates, {"reference_prefix": "R"})
        self.assertEqual(symbol, "Device:R")
        self.assertIsNone(footprint)

    def test_expand_kicad_lib_dir_user_variable(self):
        expanded = km.expand_kicad_vars(
            "${KICAD_LIB_DIR_USER}/eda-core.kicad_dbl",
            {"KICAD_LIB_DIR_USER": "/opt/kicad-lib"},
        )

        self.assertEqual(expanded, "/opt/kicad-lib/eda-core.kicad_dbl")

    def test_read_kicad_env_vars_from_common_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "kicad_common.json"
            config.write_text(
                """
                {
                  "environment": {
                    "vars": {
                      "KICAD_LIB_DIR_USER": "/home/test/KiCAD/Lib"
                    }
                  }
                }
                """,
                encoding="utf-8",
            )

            self.assertEqual(
                km.read_kicad_env_vars(config),
                {"KICAD_LIB_DIR_USER": "/home/test/KiCAD/Lib"},
            )

    def test_prompt_password_overrides_password_from_dbl(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbl = Path(tmp) / "eda-core.kicad_dbl"
            dbl.write_text(
                """
                {
                  "source": {
                    "connection_string": "Server=db.example;Port=54320;Database=altium_components;Uid=kicad_readonly;Pwd=readonly_secret;"
                  }
                }
                """,
                encoding="utf-8",
            )

            args = km.parse_args(
                [
                    "connection",
                    "--dbl",
                    str(dbl),
                    "--db-user",
                    "altium_admin",
                    "--prompt-password",
                ]
            )
            old_getpass = km.getpass.getpass
            km.getpass.getpass = lambda _prompt: "admin_secret"
            try:
                config = km.build_db_config(args)
            finally:
                km.getpass.getpass = old_getpass

            self.assertEqual(config.user, "altium_admin")
            self.assertEqual(config.password, "admin_secret")

    def test_required_write_privileges_for_reference_and_mapping(self):
        privileges = km.required_write_privileges(
            {"reference_prefix": "R"},
            "Device:R",
            "Resistor_SMD:R_0603_1608Metric",
            False,
        )

        self.assertEqual(
            privileges,
            [
                ("public.library", "UPDATE"),
                ("public.component_cad_mapping", "DELETE"),
                ("public.component_cad_mapping", "INSERT"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
