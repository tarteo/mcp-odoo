import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp_odoo.config import ALWAYS_AVAILABLE_TOOLS, ConfigError, parse_config
from mcp_odoo.odoo_client import Json2Adapter, LegacyRpcAdapter, OdooError, adapter_for
from mcp_odoo.server import configure, create_record, exec as exec_method, mcp, record_resource


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = {
            "url": "https://odoo.example.com",
            "database": "main",
            "username": "mcp-user",
            "api_key": "secret",
            "version": "20.0",
            "whitelist": [],
        }

    def config(self, whitelist: list[str] | None = None, version: str | None = None):
        values = {**self.instance, "whitelist": whitelist or []}
        if version:
            values["version"] = version
        return parse_config(values, Path("/tmp/config.yaml"))

    def test_only_whitelisted_tools_and_always_available_tools_are_registered(self) -> None:
        whitelist = ["search_records", "post_message", "exec"]
        configure(self.config(whitelist))
        names = set(mcp._tool_manager._tools)
        self.assertEqual(names, ALWAYS_AVAILABLE_TOOLS | set(whitelist))
        self.assertEqual(len(mcp._resource_manager._templates), 3)

    def test_reconfigure_removes_tools_not_in_the_new_whitelist(self) -> None:
        configure(self.config(["create_record", "delete_record"]))
        configure(self.config(["read_record"]))
        self.assertEqual(set(mcp._tool_manager._tools), ALWAYS_AVAILABLE_TOOLS | {"read_record"})

    def test_unwhitelisted_tool_is_not_registered(self) -> None:
        configure(self.config())
        self.assertNotIn("create_record", mcp._tool_manager._tools)

    def test_allowed_mutation_uses_the_single_configured_connection(self) -> None:
        configure(self.config(["create_record"]))
        with patch("mcp_odoo.server.OdooClient") as client:
            client.return_value.call.return_value = 7
            result = create_record("res.partner", {"name": "Example"})
        self.assertEqual(result, 7)
        client.assert_called_once_with(self.config(["create_record"]).instance)

    def test_exec_calls_public_method_with_ids_and_named_parameters(self) -> None:
        configure(self.config(["exec"]))
        with patch("mcp_odoo.server.OdooClient") as client:
            client.return_value.call_public.return_value = True
            result = exec_method("sale.order", "action_confirm", [7], {"context": {"lang": "en_US"}})

        self.assertIs(result, True)
        client.assert_called_once_with(self.config(["exec"]).instance)
        client.return_value.call_public.assert_called_once_with(
            "sale.order", "action_confirm", [7], {"context": {"lang": "en_US"}}
        )

    def test_exec_rejects_private_methods_and_reserved_ids_parameter(self) -> None:
        configure(self.config(["exec"]))
        with self.assertRaisesRegex(ValueError, "private"):
            exec_method("sale.order", "_private_method")
        with self.assertRaisesRegex(ValueError, "ids argument"):
            exec_method("sale.order", "action_confirm", params={"ids": [7]})

    def test_resources_require_the_corresponding_whitelisted_tool(self) -> None:
        configure(self.config())
        with self.assertRaisesRegex(ConfigError, "resource access requires 'read_record'"):
            record_resource("res.partner", "7")

    def test_json2_maps_rpc_arguments_to_http_request(self) -> None:
        instance = self.config().instance
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

    def test_json2_exec_posts_ids_and_named_parameters_for_arbitrary_method(self) -> None:
        instance = self.config().instance
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"true"

        with patch("mcp_odoo.odoo_client.urlopen", return_value=response) as open_url:
            result = Json2Adapter(instance).call_public(
                "sale.order", "action_confirm", [7], {"context": {"lang": "en_US"}}
            )

        request = open_url.call_args.args[0]
        self.assertIs(result, True)
        self.assertEqual(json.loads(request.data), {"ids": [7], "context": {"lang": "en_US"}})
        self.assertTrue(request.full_url.endswith("/json/2/sale.order/action_confirm"))

    def test_json2_arbitrary_calls_require_named_parameters(self) -> None:
        with self.assertRaisesRegex(OdooError, "requires named parameters"):
            Json2Adapter(self.config().instance).call("sale.order", "custom_method", [[7]], {})

    def test_legacy_create_unwraps_single_record_id(self) -> None:
        instance = self.config(version="18.0").instance
        common = MagicMock()
        common.__enter__.return_value.authenticate.return_value = 1
        objects = MagicMock()
        objects.__enter__.return_value.execute_kw.return_value = [7]

        with patch("mcp_odoo.odoo_client.xmlrpc.client.ServerProxy", side_effect=[common, objects]):
            result = LegacyRpcAdapter(instance).call("res.partner", "create", [[{"name": "Example"}]], {})

        self.assertEqual(result, 7)

    def test_legacy_exec_passes_record_ids_as_the_recordset(self) -> None:
        instance = self.config(version="18.0").instance
        common = MagicMock()
        common.__enter__.return_value.authenticate.return_value = 1
        objects = MagicMock()
        objects.__enter__.return_value.execute_kw.return_value = True

        with patch("mcp_odoo.odoo_client.xmlrpc.client.ServerProxy", side_effect=[common, objects]):
            result = LegacyRpcAdapter(instance).call_public(
                "sale.order", "action_confirm", [7, 8], {"context": {"lang": "en_US"}}
            )

        self.assertIs(result, True)
        execute_kw = objects.__enter__.return_value.execute_kw
        self.assertEqual(
            execute_kw.call_args.args[4:],
            ("action_confirm", [[7, 8]], {"context": {"lang": "en_US"}}),
        )

    def test_adapter_uses_the_configured_odoo_version(self) -> None:
        self.assertIsInstance(adapter_for(self.config().instance), Json2Adapter)
        self.assertIsInstance(adapter_for(self.config(version="18.0").instance), LegacyRpcAdapter)


if __name__ == "__main__":
    unittest.main()
