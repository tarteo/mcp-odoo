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
        for tool in (create_record, update_record, delete_record):
            mcp.add_tool(tool)
        _mutation_tools_registered = True
    elif not writable and _mutation_tools_registered:
        for name in ("create_record", "update_record", "delete_record"):
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
def list_models(instance: str | None = None) -> list[dict]:
    """List models available to the selected Odoo user."""
    return _call(
        instance,
        "ir.model",
        "search_read",
        [[]],
        {"fields": ["model", "name"], "limit": 1000, "order": "model"},
    )


@mcp.tool()
def get_model_fields(model: str, instance: str | None = None) -> dict:
    """Return field definitions for an Odoo model."""
    return _call(
        instance,
        model,
        "fields_get",
        [],
        {"attributes": ["string", "type", "required", "readonly", "relation", "selection", "help"]},
    )


@mcp.tool()
def search_records(
    model: str,
    domain: list[Any] | None = None,
    fields: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    instance: str | None = None,
) -> list[dict]:
    """Search records using an Odoo domain with bounded pagination."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset must not be negative")
    return _call(
        instance,
        model,
        "search_read",
        [domain or []],
        {"fields": fields, "limit": min(limit, 100), "offset": offset},
    )


@mcp.tool()
def read_record(
    model: str,
    record_id: int,
    fields: list[str] | None = None,
    instance: str | None = None,
) -> dict | None:
    """Read one record by ID, optionally selecting fields."""
    records = _call(instance, model, "read", [[record_id]], {"fields": fields})
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


@mcp.resource("odoo://instances/{instance}/models/{model}/records")
def model_records_resource(instance: str, model: str) -> list[dict]:
    """Recent records from an Odoo model."""
    return _call(
        instance,
        model,
        "search_read",
        [[]],
        {"limit": 20, "offset": 0},
    )


@mcp.resource("odoo://instances/{instance}/models/{model}/records/{record_id}")
def record_resource(instance: str, model: str, record_id: str) -> dict | None:
    """One Odoo record by ID."""
    records = _call(instance, model, "read", [[int(record_id)]], {})
    return records[0] if records else None