import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml


SUPPORTED_VERSIONS = ("18.0", "19.0", "20.0")
ALWAYS_AVAILABLE_TOOLS = frozenset({"config_info", "list_models", "get_model_fields"})
WHITELISTABLE_TOOLS = frozenset(
    {
        "read_messages",
        "post_message",
        "search_records",
        "read_record",
        "create_record",
        "update_record",
        "delete_record",
        "exec",
    }
)


class ConfigError(ValueError):
    """Raised when the server configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class InstanceConfig:
    url: str
    database: str
    username: str
    api_key: str
    version: str


@dataclass(frozen=True, slots=True)
class Config:
    instance: InstanceConfig
    whitelist: frozenset[str]
    log_level: str
    path: Path


def config_dir() -> Path:
    base = os.environ.get("MCP_ODOO_RC")
    return Path(base).expanduser() if base else Path.home() / ".config" / "mcp-odoo"


def config_path() -> Path:
    return config_dir() / "config.yaml"


def _mapping(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{name}: expected a mapping")
    return value


def _required_string(values: dict, key: str, name: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name}.{key}: expected a non-empty string")
    return value.strip()


def parse_config(data: object, path: Path | None = None) -> Config:
    root = _mapping(data, "config")
    url = _required_string(root, "url", "config").rstrip("/")
    parsed_url = urlsplit(url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise ConfigError("url: expected an HTTP or HTTPS URL")

    version = _required_string(root, "version", "config")
    if version not in SUPPORTED_VERSIONS:
        raise ConfigError(
            f"version: unsupported value {version!r}; "
            f"expected one of {', '.join(SUPPORTED_VERSIONS)}"
        )

    instance = InstanceConfig(
        url=url,
        database=_required_string(root, "database", "config"),
        username=_required_string(root, "username", "config"),
        api_key=_required_string(root, "api_key", "config"),
        version=version,
    )

    raw_whitelist = root.get("whitelist")
    if not isinstance(raw_whitelist, list):
        raise ConfigError("whitelist: expected a list of tool names")
    whitelist: set[str] = set()
    for tool_name in raw_whitelist:
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ConfigError("whitelist: tool names must be non-empty strings")
        tool_name = tool_name.strip()
        if tool_name not in WHITELISTABLE_TOOLS:
            allowed = ", ".join(sorted(WHITELISTABLE_TOOLS))
            raise ConfigError(
                f"whitelist: unknown or always-available tool {tool_name!r}; "
                f"choose from {allowed}"
            )
        if tool_name in whitelist:
            raise ConfigError(f"whitelist: duplicate tool name {tool_name!r}")
        whitelist.add(tool_name)

    log_level = root.get("log_level", "info")
    if not isinstance(log_level, str):
        raise ConfigError("log_level: expected a string")
    log_level = log_level.lower()
    if log_level not in ("debug", "info", "warning", "error"):
        raise ConfigError(f"log_level: unsupported value {log_level!r}")

    return Config(instance, frozenset(whitelist), log_level, path or config_path())


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        with path.open(encoding="utf-8") as config_file:
            data = yaml.safe_load(config_file)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in config file {path}: {exc}") from exc
    return parse_config(data, path=path)
