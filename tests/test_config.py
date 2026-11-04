import unittest
from pathlib import Path

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
