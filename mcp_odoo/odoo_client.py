import json
import logging
import xmlrpc.client
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import InstanceConfig

LOGGER = logging.getLogger(__name__)
RPC_TIMEOUT = 30


class OdooError(RuntimeError):
    """Raised when an Odoo RPC call fails."""


class _TimeoutTransport(xmlrpc.client.Transport):
    def make_connection(self, host: str) -> HTTPConnection:
        connection = super().make_connection(host)
        connection.timeout = RPC_TIMEOUT
        return connection


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def make_connection(self, host: str) -> HTTPSConnection:
        connection = super().make_connection(host)
        connection.timeout = RPC_TIMEOUT
        return connection


class LegacyRpcAdapter:
    """Odoo XML-RPC API used by Odoo 18 and 19."""

    def __init__(self, instance: InstanceConfig):
        self.instance = instance

    def call(self, model: str, method: str, args: list, kwargs: dict) -> object:
        common_url = f"{self.instance.url}/xmlrpc/2/common"
        object_url = f"{self.instance.url}/xmlrpc/2/object"
        transport = _TimeoutSafeTransport() if self.instance.url.startswith("https:") else _TimeoutTransport()
        try:
            with xmlrpc.client.ServerProxy(
                common_url, transport=transport, allow_none=True, use_builtin_types=True
            ) as common:
                user_id = common.authenticate(
                    self.instance.database,
                    self.instance.username,
                    self.instance.api_key,
                    {},
                )
            if not user_id:
                raise OdooError("Odoo authentication failed")
            with xmlrpc.client.ServerProxy(
                object_url, transport=transport, allow_none=True, use_builtin_types=True
            ) as objects:
                result = objects.execute_kw(
                    self.instance.database,
                    user_id,
                    self.instance.api_key,
                    model,
                    method,
                    args,
                    kwargs,
                )
            if method == "create" and isinstance(result, list) and len(result) == 1:
                return result[0]
            return result
        except OdooError:
            raise
        except (OSError, xmlrpc.client.Error) as exc:
            LOGGER.debug("Odoo XML-RPC call failed: %s", exc)
            raise OdooError(f"Odoo XML-RPC call failed: {exc}") from exc


@dataclass(frozen=True, slots=True)
class _Json2Method:
    parameters: tuple[str, ...]


class Json2Adapter:
    """Odoo JSON-2 API used by Odoo 20."""

    _METHODS = {
        "search": _Json2Method(("domain", "offset", "limit", "order")),
        "search_read": _Json2Method(("domain", "fields", "offset", "limit", "order")),
        "read": _Json2Method(("ids", "fields")),
        "create": _Json2Method(("vals_list",)),
        "write": _Json2Method(("ids", "vals")),
        "unlink": _Json2Method(("ids",)),
        "message_post": _Json2Method(("ids",)),
        "fields_get": _Json2Method(("allfields", "attributes")),
    }

    def __init__(self, instance: InstanceConfig):
        self.instance = instance

    def call(self, model: str, method: str, args: list, kwargs: dict) -> object:
        try:
            method_spec = self._METHODS[method]
        except KeyError:
            raise OdooError(f"unsupported Odoo JSON-2 method: {method}") from None

        parameters = dict(kwargs)
        for key, value in zip(method_spec.parameters, args):
            parameters.setdefault(key, value)

        url = (
            f"{self.instance.url}/json/2/{quote(model, safe='')}/"
            f"{quote(method, safe='')}"
        )
        request = Request(
            url,
            data=json.dumps(parameters).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.instance.api_key}",
                "X-Odoo-Database": self.instance.database,
                "Content-Type": "application/json",
                "User-Agent": "mcp-odoo",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=RPC_TIMEOUT) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OdooError(f"Odoo JSON-2 request failed ({exc.code}): {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OdooError(f"Odoo JSON-2 request failed: {exc}") from exc

        if method == "create" and isinstance(result, list) and len(result) == 1:
            return result[0]
        return result


def adapter_for(instance: InstanceConfig) -> LegacyRpcAdapter | Json2Adapter:
    if instance.version in ("18.0", "19.0"):
        return LegacyRpcAdapter(instance)
    if instance.version == "20.0":
        return Json2Adapter(instance)
    raise OdooError(f"unsupported configured Odoo version: {instance.version}")


class OdooClient:
    def __init__(self, instance: InstanceConfig):
        self.adapter = adapter_for(instance)

    def call(self, model: str, method: str, args: list | None = None, kwargs: dict | None = None) -> object:
        return self.adapter.call(model, method, args or [], kwargs or {})