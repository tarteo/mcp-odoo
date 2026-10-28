import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml


SUPPORTED_VERSIONS = ("18.0", "19.0", "20.0")


class ConfigError(ValueError):
    """Raised when the server configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class InstanceConfig:
    name: str
    url: str
    database: str
    username: str
    api_key: str
    version: str
    readonly: bool = False


@dataclass(frozen=True, slots=True)
class Config:
    instances: dict[str, InstanceConfig]
    log_level: str
    path: Path

    def resolve_instance(self, name: str | None) -> InstanceConfig:
        if name is None:
            if len(self.instances) != 1:
                raise ConfigError("instance is required when multiple instances are configured")
            return next(iter(self.instances.values()))
        try:
            return self.instances[name]
        except KeyError:
            raise ConfigError(f"unknown instance: {name}") from None


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
    raw_instances = _mapping(root.get("instances"), "instances")
    if not raw_instances:
        raise ConfigError("instances: expected at least one configured instance")

    instances: dict[str, InstanceConfig] = {}
    for name, raw_instance in raw_instances.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("instances: instance names must be non-empty strings")
        name = name.strip()
        section = _mapping(raw_instance, f"instances.{name}")
        url = _required_string(section, "url", f"instances.{name}").rstrip("/")
        parsed_url = urlsplit(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ConfigError(f"instances.{name}.url: expected an HTTP or HTTPS URL")

        version = _required_string(section, "version", f"instances.{name}")
        if version not in SUPPORTED_VERSIONS:
            raise ConfigError(
                f"instances.{name}.version: unsupported value {version!r}; "
                f"expected one of {', '.join(SUPPORTED_VERSIONS)}"
            )
        readonly = section.get("readonly", False)
        if not isinstance(readonly, bool):
            raise ConfigError(f"instances.{name}.readonly: expected a boolean")

        instances[name] = InstanceConfig(
            name=name,
            url=url,
            database=_required_string(section, "database", f"instances.{name}"),
            username=_required_string(section, "username", f"instances.{name}"),
            api_key=_required_string(section, "api_key", f"instances.{name}"),
            version=version,
            readonly=readonly,
        )

    log_level = root.get("log_level", "info")
    if not isinstance(log_level, str):
        raise ConfigError("log_level: expected a string")
    log_level = log_level.lower()
    if log_level not in ("debug", "info", "warning", "error"):
        raise ConfigError(f"log_level: unsupported value {log_level!r}")

    return Config(instances, log_level, path or config_path())


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