import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REGISTRY_DIR = Path(__file__).parent.parent / "registry"
_PARAMETER_TYPES = {"array", "boolean", "integer", "number", "object", "string"}
_PARAMETER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_METHOD_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class RegistryError(ValueError):
    """Raised when an Odoo method registry is invalid."""


@dataclass(frozen=True, slots=True)
class MethodSpec:
    model: str
    method: str
    description: str
    parameters: dict[str, dict[str, Any]]

    @property
    def tool_name(self) -> str:
        return f"odoo_{self.model}_{self.method}".replace(".", "_")


def _mapping(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise RegistryError(f"{name}: expected a mapping")
    return value


def _validate_parameter(value: object, name: str) -> dict[str, Any]:
    parameter = _mapping(value, name)
    unknown = set(parameter) - {"type", "description", "required", "items"}
    if unknown:
        raise RegistryError(f"{name}: unsupported keys: {', '.join(sorted(unknown))}")

    parameter_type = parameter.get("type")
    if parameter_type not in _PARAMETER_TYPES:
        allowed = ", ".join(sorted(_PARAMETER_TYPES))
        raise RegistryError(f"{name}.type: expected one of {allowed}")

    description = parameter.get("description", "")
    if not isinstance(description, str):
        raise RegistryError(f"{name}.description: expected a string")

    required = parameter.get("required", True)
    if not isinstance(required, bool):
        raise RegistryError(f"{name}.required: expected a boolean")

    result: dict[str, Any] = {
        "type": parameter_type,
        "description": description,
        "required": required,
    }
    if parameter_type == "array":
        if "items" not in parameter:
            raise RegistryError(f"{name}.items: required for array parameters")
        result["items"] = _validate_parameter(parameter["items"], f"{name}.items")
    elif "items" in parameter:
        raise RegistryError(f"{name}.items: only valid for array parameters")
    return result


def load_method_registry(version: str) -> dict[str, MethodSpec]:
    return load_method_registry_file(REGISTRY_DIR / f"{version}.yaml")


def load_method_registry_file(path: Path) -> dict[str, MethodSpec]:
    try:
        with path.open(encoding="utf-8") as registry_file:
            root = yaml.safe_load(registry_file)
    except FileNotFoundError:
        raise RegistryError(f"method registry file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise RegistryError(f"invalid YAML in method registry {path}: {exc}") from exc

    root = _mapping(root, f"method registry {path}")
    return parse_method_registry(root, f"method registry {path}")


def parse_method_registry(raw_methods: object, source: str) -> dict[str, MethodSpec]:
    methods = _mapping(raw_methods, source)
    registry: dict[str, MethodSpec] = {}
    tool_names: set[str] = set()

    for key, raw_spec in methods.items():
        if not isinstance(key, str) or not key.strip():
            raise RegistryError("method registry keys must be non-empty strings")
        model, separator, method = key.strip().rpartition(".")
        if not separator or not model.strip() or not _METHOD_NAME.fullmatch(method):
            raise RegistryError(
                f"method registry key {key!r} must be a model name followed by a public method name"
            )
        if method.startswith("_"):
            raise RegistryError(f"method registry key {key!r} cannot expose a private method")

        spec = _mapping(raw_spec, f"{source}.{key}")
        unknown = set(spec) - {"description", "parameters"}
        if unknown:
            raise RegistryError(f"{source}.{key}: unsupported keys: {', '.join(sorted(unknown))}")
        description = spec.get("description")
        if not isinstance(description, str) or not description.strip():
            raise RegistryError(f"{source}.{key}.description: expected a non-empty string")

        raw_parameters = _mapping(spec.get("parameters"), f"{source}.{key}.parameters")
        parameters: dict[str, dict[str, Any]] = {}
        for parameter_name, parameter_spec in raw_parameters.items():
            if not isinstance(parameter_name, str) or not _PARAMETER_NAME.fullmatch(parameter_name):
                raise RegistryError(
                    f"{source}.{key}: parameter names must be valid public identifiers"
                )
            if parameter_name.startswith("_"):
                raise RegistryError(f"{source}.{key}: private parameters cannot be exposed")
            parameters[parameter_name] = _validate_parameter(
                parameter_spec, f"{source}.{key}.parameters.{parameter_name}"
            )

        method_spec = MethodSpec(model, method, description.strip(), parameters)
        if method_spec.tool_name in tool_names:
            raise RegistryError(f"{source}.{key}: generated tool name is not unique")
        tool_names.add(method_spec.tool_name)
        registry[key.strip()] = method_spec

    return registry
