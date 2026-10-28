import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp_odoo.config import ConfigError, parse_config
from mcp_odoo.odoo_client import Json2Adapter, LegacyRpcAdapter, adapter_for
from mcp_odoo.server import configure, create_record, mcp


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = {
            "url": "https://odoo.example.com",
            "database": "main",
            "username": "mcp-user",
            "api_key": "secret",
            "version": "20.0",
        }

    def config(self, instances: dict):
        return parse_config({"instances": instances}, Path("/tmp/config.yaml"))

    def test_all_readonly_instances_omit_mutation_tools(self) -> None:
        instance = {**self.instance, "readonly": True}
        configure(self.config({"locked": instance}))
        names = set(mcp._tool_manager._tools)
        self.assertTrue({"config_info", "list_models", "get_model_fields", "search_records", "read_record"} <= names)
        self.assertFalse({"create_record", "update_record", "delete_record"} & names)
        self.assertEqual(len(mcp._resource_manager._templates), 2)

    def test_mutation_tools_exist_for_mixed_instances_but_enforce_readonly(self) -> None:
        locked = {**self.instance, "readonly": True}
        writable = {**self.instance, "version": "18.0", "readonly": False}
        configure(self.config({"locked": locked, "writable": writable}))
        create = mcp._tool_manager._tools["create_record"].fn
        self.assertIsInstance(adapter_for(self.config({"locked": locked}).instances["locked"]), Json2Adapter)
        self.assertIsInstance(adapter_for(self.config({"writable": writable}).instances["writable"]), LegacyRpcAdapter)
        with patch("mcp_odoo.server.OdooClient") as client:
            with self.assertRaisesRegex(ConfigError, "read-only"):
                create("res.partner", {"name": "Example"}, instance="locked")
            client.assert_not_called()

    def test_json2_maps_rpc_arguments_to_http_request(self) -> None:
        instance = self.config({"company": self.instance}).instances["company"]
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"[{\"id\": 7}]"

        with patch("mcp_odoo.odoo_client.urlopen", return_value=response) as open_url:
            result = Json2Adapter(instance).call(
                "res.partner",
                "search_read",
                [[]],
                {"fields": ["name"], "limit": 4},
            )

        request = open_url.call_args.args[0]
        self.assertEqual(result, [{"id": 7}])
        self.assertEqual(
            request.full_url,
            "https://odoo.example.com/json/2/res.partner/search_read",
        )
        self.assertEqual(
            json.loads(request.data),
            {"domain": [], "fields": ["name"], "limit": 4},
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(request.get_header("X-odoo-database"), "main")


if __name__ == "__main__":
    unittest.main()