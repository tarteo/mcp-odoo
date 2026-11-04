import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import ALWAYS_AVAILABLE_TOOLS, Config, ConfigError, load_config
from .odoo_client import OdooClient

mcp = FastMCP("odoo")
_config: Config | None = None
_registered_tool_names: set[str] = set()


def configure(config: Config) -> None:
    global _config
    _config = config
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, config.log_level.upper()),
    )

    enabled_names = ALWAYS_AVAILABLE_TOOLS | config.whitelist
    for name in _registered_tool_names - enabled_names:
        mcp.remove_tool(name)
        _registered_tool_names.remove(name)
    for name in enabled_names - _registered_tool_names:
        mcp.add_tool(_TOOL_FUNCTIONS[name])
        _registered_tool_names.add(name)


def _cfg() -> Config:
    global _config
    if _config is None:
        _config = load_config()
        logging.basicConfig(
            stream=sys.stderr,
            level=getattr(logging, _config.log_level.upper()),
        )
    return _config


def _require_resource_permission(tool_name: str) -> None:
    if tool_name not in _cfg().whitelist:
        raise ConfigError(f"resource access requires {tool_name!r} in the whitelist")


def _call(
    model: str,
    method: str,
    args: list | None = None,
    kwargs: dict | None = None,
) -> object:
    return OdooClient(_cfg().instance).call(model, method, args, kwargs)


def _readable_fields(
    model: str,
    fields: list[str] | None,
) -> list[str] | None:
    """Explicit fields win; otherwise list all non-binary fields of the model."""
    if fields:
        return fields
    records = _call(
        "ir.model.fields",
        "search_read",
        [[("model", "=", model), ("ttype", "!=", "binary")]],
        {"fields": ["name"]},
    )
    return [record["name"] for record in records] or None


@mcp.tool()
def config_info() -> dict:
    """Show the config path and connection details without the API key."""
    config = _cfg()
    return {
        "path": str(config.path),
        "exists": config.path.is_file(),
        "connection": {
            "url": config.instance.url,
            "database": config.instance.database,
            "version": config.instance.version,
        },
        "whitelist": sorted(config.whitelist),
    }


@mcp.tool()
def list_models(
    search: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Search models by technical name or label (case-insensitive substring). Omit search to list the first models."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    domain = ['|', ("model", "ilike", search), ("name", "ilike", search)] if search else []
    return _call(
        "ir.model",
        "search_read",
        [domain],
        {"fields": ["model", "name"], "limit": min(limit, 200), "order": "model"},
    )


@mcp.tool()
def get_model_fields(
    model: str,
    search: str | None = None,
    limit: int = 50,
) -> dict:
    """Return field definitions for an Odoo model, filtered by a case-insensitive substring of the field name or label."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    domain: list[Any] = [("model", "=", model)]
    if search:
        domain += ["|", ("name", "ilike", search), ("field_description", "ilike", search)]
    records = _call(
        "ir.model.fields",
        "search_read",
        [domain],
        {
            "fields": ["name", "field_description", "ttype", "required", "readonly", "relation", "help"],
            "limit": min(limit, 200),
            "order": "name",
        },
    )
    return {
        record["name"]: {
            "string": record["field_description"],
            "type": record["ttype"],
            "required": record["required"],
            "readonly": record["readonly"],
            "relation": record["relation"] or None,
            "help": record["help"] or None,
        }
        for record in records
    }


@mcp.tool()
def search_records(
    model: str,
    domain: list[Any] | None = None,
    fields: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Search records using an Odoo domain with bounded pagination. Binary/image fields are omitted unless listed in fields."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset must not be negative")
    return _call(
        model,
        "search_read",
        [domain or []],
        {
            "fields": _readable_fields(model, fields),
            "limit": min(limit, 100),
            "offset": offset,
        },
    )


@mcp.tool()
def read_record(
    model: str,
    record_id: int,
    fields: list[str] | None = None,
) -> dict | None:
    """Read one record by ID. Binary/image fields are omitted unless listed in fields."""
    records = _call(
        model,
        "read",
        [[record_id]],
        {"fields": _readable_fields(model, fields)},
    )
    return records[0] if records else None


@mcp.tool()
def create_record(model: str, values: dict[str, Any]) -> int:
    """Create a record and return its new Odoo ID."""
    return _call(model, "create", [[values]])


@mcp.tool()
def update_record(
    model: str,
    record_id: int,
    values: dict[str, Any],
) -> bool:
    """Update a record using Odoo field names and values."""
    return _call(model, "write", [[record_id], values])


@mcp.tool()
def delete_record(model: str, record_id: int) -> bool:
    """Permanently delete a record from Odoo."""
    return _call(model, "unlink", [[record_id]])


@mcp.tool()
def exec(
    model: str,
    method: str,
    ids: list[int] | None = None,
    params: dict[str, Any] | None = None,
) -> object:
    """Call a public Odoo model method with optional record IDs and named parameters."""
    if not model.strip():
        raise ValueError("model must not be empty")
    if not method.strip():
        raise ValueError("method must not be empty")
    if method.startswith("_"):
        raise ValueError("private Odoo methods cannot be called")
    if ids is not None and (
        not isinstance(ids, list)
        or any(not isinstance(record_id, int) or isinstance(record_id, bool) for record_id in ids)
    ):
        raise ValueError("ids must be a list of integers")
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    params = params or {}
    if any(not isinstance(key, str) for key in params):
        raise ValueError("params keys must be strings")
    if "ids" in params:
        raise ValueError("pass record IDs using the ids argument")
    return OdooClient(_cfg().instance).call_public(model, method, ids, params)


_MESSAGE_FIELDS = ["id", "date", "author_id", "message_type", "subtype_id", "subject", "body"]


def _messages(model: str, record_id: int, limit: int, offset: int) -> list[dict]:
    return _call(
        "mail.message",
        "search_read",
        [[("model", "=", model), ("res_id", "=", record_id)]],
        {"fields": _MESSAGE_FIELDS, "limit": limit, "offset": offset, "order": "date desc, id desc"},
    )


@mcp.tool()
def read_messages(
    model: str,
    record_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Read chatter messages (newest first) of a record whose model inherits mail.thread."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset must not be negative")
    return _messages(model, record_id, min(limit, 100), offset)


@mcp.tool()
def post_message(
    model: str,
    record_id: int,
    body: str,
    internal_note: bool = False,
) -> int:
    """Post a message (or internal note) on a mail.thread record and return the message ID."""
    return _call(
        model,
        "message_post",
        [[record_id]],
        {
            "body": body,
            "message_type": "comment",
            "subtype_xmlid": "mail.mt_note" if internal_note else "mail.mt_comment",
        },
    )


_TOOL_FUNCTIONS = {
    "config_info": config_info,
    "list_models": list_models,
    "get_model_fields": get_model_fields,
    "read_messages": read_messages,
    "post_message": post_message,
    "search_records": search_records,
    "read_record": read_record,
    "create_record": create_record,
    "update_record": update_record,
    "delete_record": delete_record,
    "exec": exec,
}
_registered_tool_names.update(_TOOL_FUNCTIONS)


@mcp.resource("odoo://models/{model}/records/{record_id}/messages")
def record_messages_resource(model: str, record_id: str) -> list[dict]:
    """Latest 20 chatter messages of a record."""
    _require_resource_permission("read_messages")
    return _messages(model, int(record_id), 20, 0)


@mcp.resource("odoo://models/{model}/records")
def model_records_resource(model: str) -> list[dict]:
    """Recent records from an Odoo model."""
    _require_resource_permission("search_records")
    return _call(
        model,
        "search_read",
        [[]],
        {"fields": _readable_fields(model, None), "limit": 20, "offset": 0},
    )


@mcp.resource("odoo://models/{model}/records/{record_id}")
def record_resource(model: str, record_id: str) -> dict | None:
    """One Odoo record by ID."""
    _require_resource_permission("read_record")
    records = _call(
        model,
        "read",
        [[int(record_id)]],
        {"fields": _readable_fields(model, None)},
    )
    return records[0] if records else None
