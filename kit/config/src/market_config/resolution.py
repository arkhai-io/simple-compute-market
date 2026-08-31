"""Strict layered resolution for role-specific typed configuration models."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from collections.abc import Mapping as MappingABC
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Generic, TypeVar, cast, get_args, get_origin

from pydantic import BaseModel, SecretBytes, SecretStr

ModelT = TypeVar("ModelT", bound=BaseModel)


class ConfigResolutionError(ValueError):
    """A typed configuration layer violates its declared model contract."""


class ConfigLayer(str, Enum):
    """Declared low-to-high configuration sources."""

    DEFAULTS = "defaults"
    TOML = "toml"
    SECRET = "secret"
    ENVIRONMENT = "environment"
    CLI = "cli"


@dataclass(frozen=True, slots=True)
class ConfigFieldSource:
    """Safe field provenance containing no resolved value."""

    path: str
    layer: ConfigLayer
    secret: bool

    def safe_projection(self) -> dict[str, str | bool]:
        return {"path": self.path, "source": self.layer.value, "secret": self.secret}


@dataclass(frozen=True, slots=True)
class ModelSurfaceField:
    """Model metadata used to generate role configuration surfaces."""

    path: str
    annotation: str
    required: bool
    default: Any
    secret: bool
    roles: frozenset[str]
    description: str | None
    environment: str | None
    list_replaces: bool

    def safe_projection(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "annotation": self.annotation,
            "required": self.required,
            "default": "<redacted>" if self.secret and self.default is not None else self.default,
            "secret": self.secret,
            "roles": sorted(self.roles),
            "description": self.description,
            "environment": self.environment,
            "list_replaces": self.list_replaces,
        }


@dataclass(frozen=True, slots=True)
class ResolvedConfig(Generic[ModelT]):
    """A validated model together with value-free source metadata."""

    value: ModelT
    sources: Mapping[str, ConfigFieldSource]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))

    def source_projection(self) -> dict[str, dict[str, str | bool]]:
        return {path: self.sources[path].safe_projection() for path in sorted(self.sources)}

    def redacted_projection(self) -> dict[str, Any]:
        return _project_model(self.value, omit_secrets=False)

    def public_projection(self) -> dict[str, Any]:
        return _project_model(self.value, omit_secrets=True)

    def public_fingerprint(self) -> str:
        payload = json.dumps(
            self.public_projection(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def resolve_model(
    model: type[ModelT],
    *,
    defaults: Mapping[str, Any] | None = None,
    toml: Mapping[str, Any] | None = None,
    secrets: Mapping[str, Any] | None = None,
    environment: Mapping[str, Any] | None = None,
    cli: Mapping[str, Any] | None = None,
    role: str | None = None,
) -> ResolvedConfig[ModelT]:
    """Resolve CLI > environment/Secret > TOML > defaults strictly.

    Environment and Secret share one tier. They may provide disjoint fields;
    overlapping paths fail rather than acquiring an undeclared order. Mapping
    values merge recursively, while a higher list replaces the whole lower list.
    """
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise TypeError("model must be a Pydantic BaseModel type")
    layers: tuple[tuple[ConfigLayer, Mapping[str, Any]], ...] = tuple(
        (layer, values)
        for layer, values in (
            (ConfigLayer.DEFAULTS, defaults or {}),
            (ConfigLayer.TOML, toml or {}),
            (ConfigLayer.SECRET, secrets or {}),
            (ConfigLayer.ENVIRONMENT, environment or {}),
            (ConfigLayer.CLI, cli or {}),
        )
        if values
    )
    for layer, values in layers:
        if not isinstance(values, Mapping):
            raise ConfigResolutionError(f"{layer.value} layer must be a mapping")
        _validate_layer(model, values, layer=layer, role=role, path="")
    collisions = sorted(_leaf_paths(secrets or {}) & _leaf_paths(environment or {}))
    if collisions:
        raise ConfigResolutionError(
            "environment and Secret both set same-precedence fields: " + ", ".join(collisions)
        )

    merged: dict[str, Any] = {}
    sources: dict[str, ConfigFieldSource] = {}
    for layer, values in layers:
        _merge(merged, values)
        for path in _leaf_paths(values):
            field_info = _field_for_path(model, path)
            sources[path] = ConfigFieldSource(
                path=path, layer=layer, secret=_field_is_secret(field_info)
            )
    try:
        value = model.model_validate(merged)
    except ValueError as exc:
        raise ConfigResolutionError(f"invalid {model.__name__} configuration: {exc}") from exc

    for surface in model_surface(model, role=role, include_secrets=True):
        if surface.path not in sources and not _has_descendant_source(surface.path, sources):
            sources[surface.path] = ConfigFieldSource(
                path=surface.path, layer=ConfigLayer.DEFAULTS, secret=surface.secret
            )
    return ResolvedConfig(value=value, sources=sources)


def model_surface(
    model: type[BaseModel],
    *,
    role: str | None,
    include_secrets: bool = False,
) -> tuple[ModelSurfaceField, ...]:
    """Return deterministic dotted-field metadata without mechanism imports."""
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise TypeError("model must be a Pydantic BaseModel type")
    fields: list[ModelSurfaceField] = []
    _collect_surface(
        model, path="", role=role, include_secrets=include_secrets, output=fields
    )
    return tuple(sorted(fields, key=lambda item: item.path))


def _collect_surface(
    model: type[BaseModel],
    *,
    path: str,
    role: str | None,
    include_secrets: bool,
    output: list[ModelSurfaceField],
) -> None:
    for name, field_info in model.model_fields.items():
        roles = _field_roles(field_info)
        if role is not None and role not in roles:
            continue
        secret = _field_is_secret(field_info)
        if secret and not include_secrets:
            continue
        field_path = f"{path}.{name}" if path else name
        extra = field_info.json_schema_extra
        environment = None
        if isinstance(extra, Mapping):
            candidate = extra.get("environment") or extra.get("env")
            if isinstance(candidate, str):
                environment = candidate
        default = None
        if not field_info.is_required():
            default = _json_safe(field_info.get_default(call_default_factory=True))
            if secret and default is not None:
                default = "<redacted>"
        output.append(
            ModelSurfaceField(
                path=field_path,
                annotation=_annotation_name(field_info.annotation),
                required=field_info.is_required(),
                default=default,
                secret=secret,
                roles=roles,
                description=field_info.description,
                environment=environment,
                list_replaces=_is_list_annotation(field_info.annotation),
            )
        )
        nested = _nested_model(field_info.annotation)
        if nested is not None:
            container = _model_container(field_info.annotation)
            nested_path = field_path
            if container == "mapping":
                nested_path += ".*"
            elif container == "sequence":
                nested_path += "[]"
            _collect_surface(
                nested,
                path=nested_path,
                role=role,
                include_secrets=include_secrets,
                output=output,
            )


def _validate_layer(
    model: type[BaseModel],
    values: Mapping[str, Any],
    *,
    layer: ConfigLayer,
    role: str | None,
    path: str,
) -> None:
    aliases: dict[str, tuple[str, Any]] = {}
    for name, field_info in model.model_fields.items():
        aliases[name] = (name, field_info)
        if isinstance(field_info.alias, str):
            aliases[field_info.alias] = (name, field_info)
    unknown = sorted(str(key) for key in values if key not in aliases)
    if unknown:
        location = path or model.__name__
        raise ConfigResolutionError(
            f"unknown {location} keys in {layer.value}: {', '.join(unknown)}"
        )
    for key, item in values.items():
        name, field_info = aliases[cast(str, key)]
        field_path = f"{path}.{name}" if path else name
        if role is not None and role not in _field_roles(field_info):
            raise ConfigResolutionError(f"{field_path} does not apply to role {role!r}")
        if _field_is_secret(field_info) and layer not in {
            ConfigLayer.SECRET,
            ConfigLayer.ENVIRONMENT,
        }:
            raise ConfigResolutionError(
                f"secret field {field_path} cannot come from {layer.value}"
            )
        nested = _nested_model(field_info.annotation)
        container = _model_container(field_info.annotation)
        if nested is not None and container == "mapping" and isinstance(item, Mapping):
            for dynamic_key, nested_item in item.items():
                if isinstance(nested_item, Mapping):
                    _validate_layer(
                        nested,
                        nested_item,
                        layer=layer,
                        role=role,
                        path=f"{field_path}.{dynamic_key}",
                    )
        elif nested is not None and container == "sequence" and isinstance(item, (list, tuple)):
            for index, nested_item in enumerate(item):
                if isinstance(nested_item, Mapping):
                    _validate_layer(
                        nested,
                        nested_item,
                        layer=layer,
                        role=role,
                        path=f"{field_path}[{index}]",
                    )
        elif nested is not None and isinstance(item, Mapping):
            _validate_layer(nested, item, layer=layer, role=role, path=field_path)


def _merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> None:
    for key, value in overlay.items():
        existing = base.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            _merge(existing, value)
        elif isinstance(value, Mapping):
            nested: dict[str, Any] = {}
            _merge(nested, value)
            base[key] = nested
        elif isinstance(value, (list, tuple)):
            base[key] = list(value)
        else:
            base[key] = value


def _leaf_paths(values: Mapping[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping) and value:
            paths.update(_leaf_paths(value, path))
        else:
            paths.add(path)
    return paths


def _field_for_path(model: type[BaseModel], path: str) -> Any:
    current = model
    field_info: Any = None
    components = path.split(".")
    index = 0
    while index < len(components):
        component = components[index].split("[", 1)[0]
        field_info = current.model_fields.get(component)
        if field_info is None:
            field_info = next(
                (field for field in current.model_fields.values() if field.alias == component),
                None,
            )
        if field_info is None:
            raise ConfigResolutionError(f"unknown field path {path!r}")
        nested = _nested_model(field_info.annotation)
        container = _model_container(field_info.annotation)
        if nested is not None:
            current = nested
        index += 1
        if container == "mapping" and index < len(components):
            index += 1
    return field_info


def _has_descendant_source(path: str, sources: Mapping[str, ConfigFieldSource]) -> bool:
    prefix = path + "."
    return any(candidate.startswith(prefix) for candidate in sources)


def _field_roles(field_info: Any) -> frozenset[str]:
    extra = field_info.json_schema_extra
    if isinstance(extra, Mapping):
        roles = extra.get("roles")
        if isinstance(roles, (list, tuple, set, frozenset)):
            return frozenset(str(role) for role in roles)
    return frozenset({"buyer", "seller"})


def _field_is_secret(field_info: Any) -> bool:
    extra = field_info.json_schema_extra
    if isinstance(extra, Mapping) and extra.get("secret") is True:
        return True
    annotation = field_info.annotation
    if annotation in (SecretStr, SecretBytes):
        return True
    return any(argument in (SecretStr, SecretBytes) for argument in get_args(annotation))


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for argument in get_args(annotation):
        nested = _nested_model(argument)
        if nested is not None:
            return nested
    return None


def _is_list_annotation(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin in (list, tuple, Sequence, SequenceABC):
        return True
    return any(_is_list_annotation(argument) for argument in get_args(annotation))


def _model_container(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin in (dict, MappingABC):
        return "mapping"
    if origin in (list, tuple, Sequence, SequenceABC):
        return "sequence"
    for argument in get_args(annotation):
        nested = _model_container(argument)
        if nested != "direct":
            return nested
    return "direct"


def _annotation_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is None:
        return getattr(annotation, "__name__", str(annotation).replace("typing.", ""))
    arguments = ", ".join(_annotation_name(argument) for argument in get_args(annotation))
    name = getattr(origin, "__name__", str(origin).replace("typing.", ""))
    return f"{name}[{arguments}]"


def _json_safe(value: Any) -> Any:
    if isinstance(value, (SecretStr, SecretBytes)):
        return "<redacted>"
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _project_model(model: BaseModel, *, omit_secrets: bool) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for name, field_info in type(model).model_fields.items():
        value = getattr(model, name)
        if _field_is_secret(field_info):
            if not omit_secrets:
                projection[name] = "<redacted>" if value is not None else None
            continue
        projection[name] = _project_value(value, omit_secrets=omit_secrets)
    return projection


def _project_value(value: Any, *, omit_secrets: bool) -> Any:
    if isinstance(value, BaseModel):
        return _project_model(value, omit_secrets=omit_secrets)
    if isinstance(value, (SecretStr, SecretBytes)):
        return None if omit_secrets else "<redacted>"
    if isinstance(value, Mapping):
        return {
            str(key): _project_value(item, omit_secrets=omit_secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_project_value(item, omit_secrets=omit_secrets) for item in value]
    return _json_safe(value)
