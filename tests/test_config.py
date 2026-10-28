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
        }

    def parse(self, instances: dict) -> object:
        return parse_config({"instances": instances}, Path("/tmp/config.yaml"))

    def test_requires_supported_explicit_version(self) -> None:
        invalid = dict(self.instance)
        invalid.pop("version")
        with self.assertRaisesRegex(ConfigError, "version"):
            self.parse({"company": invalid})

        invalid["version"] = "17.0"
        with self.assertRaisesRegex(ConfigError, "unsupported"):
            self.parse({"company": invalid})

    def test_instance_selection_is_never_implicit_for_multiple_instances(self) -> None:
        config = self.parse({"one": self.instance, "two": self.instance})
        with self.assertRaisesRegex(ConfigError, "instance is required"):
            config.resolve_instance(None)
        with self.assertRaisesRegex(ConfigError, "unknown instance"):
            config.resolve_instance("missing")

    def test_single_instance_can_be_selected_by_omission(self) -> None:
        config = self.parse({"company": self.instance})
        self.assertEqual(config.resolve_instance(None).name, "company")


if __name__ == "__main__":
    unittest.main()