import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import Config, ConfigError, InstanceConfig, load_config
from .odoo_client import OdooClient

mcp = FastMCP("odoo")
_config: Config | None = None
_mutation_tools_registered = True


def configure(config: Config) -> None:
    global _config, _mutation_tools_registered
    _config = config
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, config.log_level.upper()),
    )

    writable = any(not instance.readonly for instance in config.instances.values())
    if writable and not _mutation_tools_registered:
        for tool in (create_record, update_record, delete_record, post_message):
            mcp.add_tool(tool)
        _mutation_tools_registered = True
    elif not writable and _mutation_tools_registered:
        for name in ("create_record", "update_record", "delete_record", "post_message"):
            mcp.remove_tool(name)
        _mutation_tools_registered = False


def _cfg() -> Config:
    global _config
    if _config is None:
        _config = load_config()
        logging.basicConfig(
            stream=sys.stderr,
            level=getattr(logging, _config.log_level.upper()),
        )
    return _config


def _call(
    instance: str | None,
    model: str,
    method: str,
    args: list | None = None,
    kwargs: dict | None = None,
    *,
    mutation: bool = False,
) -> object:
    selected = _cfg().resolve_instance(instance)
    if mutation and selected.readonly:
        raise ConfigError(f"instance {selected.name!r} is read-only")
    return OdooClient(selected).call(model, method, args, kwargs)


def _readable_fields(
    instance: str | None,
    model: str,
    fields: list[str] | None,
) -> list[str] | None:
    """Explicit fields win; otherwise list all non-binary fields of the model."""
    if fields:
        return fields
    records = _call(
        instance,
        "ir.model.fields",
        "search_read",
        [[("model", "=", model), ("ttype", "!=", "binary")]],
        {"fields": ["name"]},
    )
    return [record["name"] for record in records] or None


@mcp.tool()
def config_info() -> dict:
    """Show the config path and configured instance names without secrets."""
    config = _cfg()
    return {
        "path": str(config.path),
        "exists": config.path.is_file(),
        "instances": [
            {
                "name": instance.name,
                "version": instance.version,
                "readonly": instance.readonly,
            }
            for instance in config.instances.values()
        ],
    }


@mcp.tool()
def list_models(
    search: str | None = None,
    limit: int = 50,
    instance: str | None = None,
) -> list[dict]:
    """Search models by technical name or label (case-insensitive substring). Omit search to list the first models."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    domain = ['|', ("model", "ilike", search), ("name", "ilike", search)] if search else []
    return _call(
        instance,
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
    instance: str | None = None,
) -> dict:
    """Return field definitions for an Odoo model, filtered by a case-insensitive substring of the field name or label."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    domain: list[Any] = [("model", "=", model)]
    if search:
        domain += ["|", ("name", "ilike", search), ("field_description", "ilike", search)]
    records = _call(
        instance,
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
    instance: str | None = None,
) -> list[dict]:
    """Search records using an Odoo domain with bounded pagination. Binary/image fields are omitted unless listed in fields."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset must not be negative")
    return _call(
        instance,
        model,
        "search_read",
        [domain or []],
        {
            "fields": _readable_fields(instance, model, fields),
            "limit": min(limit, 100),
            "offset": offset,
        },
    )


@mcp.tool()
def read_record(
    model: str,
    record_id: int,
    fields: list[str] | None = None,
    instance: str | None = None,
) -> dict | None:
    """Read one record by ID. Binary/image fields are omitted unless listed in fields."""
    records = _call(
        instance,
        model,
        "read",
        [[record_id]],
        {"fields": _readable_fields(instance, model, fields)},
    )
    return records[0] if records else None


@mcp.tool()
def create_record(model: str, values: dict[str, Any], instance: str | None = None) -> int:
    """Create a record and return its new Odoo ID."""
    return _call(instance, model, "create", [[values]], mutation=True)


@mcp.tool()
def update_record(
    model: str,
    record_id: int,
    values: dict[str, Any],
    instance: str | None = None,
) -> bool:
    """Update a record using Odoo field names and values."""
    return _call(instance, model, "write", [[record_id], values], mutation=True)


@mcp.tool()
def delete_record(model: str, record_id: int, instance: str | None = None) -> bool:
    """Permanently delete a record from Odoo."""
    return _call(instance, model, "unlink", [[record_id]], mutation=True)


_MESSAGE_FIELDS = ["id", "date", "author_id", "message_type", "subtype_id", "subject", "body"]


def _messages(instance: str | None, model: str, record_id: int, limit: int, offset: int) -> list[dict]:
    return _call(
        instance,
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
    instance: str | None = None,
) -> list[dict]:
    """Read chatter messages (newest first) of a record whose model inherits mail.thread."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset must not be negative")
    return _messages(instance, model, record_id, min(limit, 100), offset)


@mcp.tool()
def post_message(
    model: str,
    record_id: int,
    body: str,
    internal_note: bool = False,
    instance: str | None = None,
) -> int:
    """Post a message (or internal note) on a mail.thread record and return the message ID."""
    return _call(
        instance,
        model,
        "message_post",
        [[record_id]],
        {
            "body": body,
            "message_type": "comment",
            "subtype_xmlid": "mail.mt_note" if internal_note else "mail.mt_comment",
        },
        mutation=True,
    )


@mcp.resource("odoo://instances/{instance}/models/{model}/records/{record_id}/messages")
def record_messages_resource(instance: str, model: str, record_id: str) -> list[dict]:
    """Latest 20 chatter messages of a record."""
    return _messages(instance, model, int(record_id), 20, 0)


@mcp.resource("odoo://instances/{instance}/models/{model}/records")
def model_records_resource(instance: str, model: str) -> list[dict]:
    """Recent records from an Odoo model."""
    return _call(
        instance,
        model,
        "search_read",
        [[]],
        {"fields": _readable_fields(instance, model, None), "limit": 20, "offset": 0},
    )


@mcp.resource("odoo://instances/{instance}/models/{model}/records/{record_id}")
def record_resource(instance: str, model: str, record_id: str) -> dict | None:
    """One Odoo record by ID."""
    records = _call(
        instance,
        model,
        "read",
        [[int(record_id)]],
        {"fields": _readable_fields(instance, model, None)},
    )
    return records[0] if records else None