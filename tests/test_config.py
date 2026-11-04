import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp_odoo.config import ConfigError, parse_config


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = {
            "url": "https://odoo.example.com",
            "database": "main",
            "username": "mcp-user",
            "api_key": "secret",
            "version": "18.0",
            "whitelist": [],
        }

    def parse(self, overrides: dict | None = None) -> object:
        return parse_config({**self.instance, **(overrides or {})}, Path("/tmp/config.yaml"))

    def test_requires_supported_explicit_version(self) -> None:
        invalid = dict(self.instance)
        invalid.pop("version")
        with self.assertRaisesRegex(ConfigError, "version"):
            parse_config(invalid, Path("/tmp/config.yaml"))

        invalid = {**self.instance, "version": "17.0"}
        with self.assertRaisesRegex(ConfigError, "unsupported"):
            parse_config(invalid, Path("/tmp/config.yaml"))

    def test_config_uses_flat_connection_settings(self) -> None:
        config = self.parse()
        self.assertEqual(config.instance.url, "https://odoo.example.com")
        self.assertEqual(config.instance.database, "main")
        self.assertEqual(config.whitelist, frozenset())

    def test_exec_is_an_optional_whitelistable_tool(self) -> None:
        config = self.parse({"whitelist": ["exec"]})
        self.assertEqual(config.whitelist, frozenset({"exec"}))

    def test_schedule_activity_is_an_optional_whitelistable_tool(self) -> None:
        config = self.parse({"whitelist": ["schedule_activity"]})
        self.assertEqual(config.whitelist, frozenset({"schedule_activity"}))

    def test_archive_records_is_an_optional_whitelistable_tool(self) -> None:
        config = self.parse({"whitelist": ["archive_records"]})
        self.assertEqual(config.whitelist, frozenset({"archive_records"}))

    def test_core_registry_method_can_be_whitelisted(self) -> None:
        config = self.parse({"whitelist": ["sale.order.action_confirm"]})
        spec = config.method_registry["sale.order.action_confirm"]
        self.assertEqual(spec.model, "sale.order")
        self.assertEqual(spec.method, "action_confirm")
        self.assertEqual(spec.parameters["ids"]["type"], "array")
        self.assertNotIn("crm.lead.activity_schedule", config.method_registry)
        self.assertNotIn("project.task.activity_schedule", config.method_registry)
        self.assertNotIn("project.task.action_archive", config.method_registry)

    def test_custom_registry_file_can_be_whitelisted(self) -> None:
        with TemporaryDirectory() as directory:
            registry_path = Path(directory) / "mycustom.yaml"
            registry_path.write_text(
                """sale.order.custom_operation:
  description: Run a custom operation.
  parameters:
    ids:
      type: array
      items:
        type: integer
    note:
      type: string
      required: false
""",
                encoding="utf-8",
            )
            config = self.parse(
                {
                    "whitelist": ["sale.order.custom_operation"],
                    "registry": ["registry/18.0.yaml", str(registry_path)],
                }
            )
        self.assertIn("sale.order.custom_operation", config.method_registry)
        self.assertIn("sale.order.action_confirm", config.method_registry)
        self.assertEqual(
            config.method_registry["sale.order.custom_operation"].method,
            "custom_operation",
        )

    def test_relative_registry_path_is_resolved_beside_config(self) -> None:
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            registry_path = Path(directory) / "mycustom.yaml"
            registry_path.write_text(
                """sale.order.custom_operation:
  description: Run a custom operation.
  parameters: {}
""",
                encoding="utf-8",
            )
            config = parse_config(
                {
                    **self.instance,
                    "registry": ["mycustom.yaml"],
                    "whitelist": ["sale.order.custom_operation"],
                },
                config_path,
            )
        self.assertIn("sale.order.custom_operation", config.method_registry)

    def test_registry_files_cannot_duplicate_method_entries(self) -> None:
        core_registry = Path(__file__).parent.parent / "registry" / "18.0.yaml"
        with TemporaryDirectory() as directory:
            duplicate_path = Path(directory) / "duplicate.yaml"
            duplicate_path.write_text(
                """sale.order.action_confirm:
  description: Replacement.
  parameters: {}
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "duplicate method entries"):
                self.parse({"registry": [str(core_registry), str(duplicate_path)]})

    def test_registry_file_parameter_schemas_are_validated(self) -> None:
        with TemporaryDirectory() as directory:
            registry_path = Path(directory) / "invalid.yaml"
            registry_path.write_text(
                """sale.order.custom_operation:
  description: Run a custom operation.
  parameters:
    value:
      type: unsupported
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "expected one of"):
                self.parse({"registry": [str(registry_path)]})

    def test_registry_paths_must_be_a_list(self) -> None:
        with self.assertRaisesRegex(ConfigError, "registry: expected a list"):
            self.parse({"registry": "registry/18.0.yaml"})

    def test_inline_method_definitions_are_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "define custom methods in a registry file"):
            self.parse({"methods": {}})

    def test_whitelist_requires_known_optional_tool_names(self) -> None:
        invalid = dict(self.instance)
        invalid.pop("whitelist")
        with self.assertRaisesRegex(ConfigError, "whitelist: expected a list"):
            parse_config(invalid, Path("/tmp/config.yaml"))
        with self.assertRaisesRegex(ConfigError, "whitelist: expected a list"):
            self.parse({"whitelist": None})
        with self.assertRaisesRegex(ConfigError, "unknown or always-available"):
            self.parse({"whitelist": ["not_a_tool"]})
        with self.assertRaisesRegex(ConfigError, "always-available"):
            self.parse({"whitelist": ["config_info"]})
        with self.assertRaisesRegex(ConfigError, "duplicate"):
            self.parse({"whitelist": ["search_records", "search_records"]})

    def test_legacy_multi_instance_shape_is_not_accepted(self) -> None:
        with self.assertRaisesRegex(ConfigError, "config.url"):
            parse_config({"instances": {"company": self.instance}}, Path("/tmp/config.yaml"))


if __name__ == "__main__":
    unittest.main()
