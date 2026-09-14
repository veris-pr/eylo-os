"""Environment-value parsing helpers."""

import os
from types import UnionType
from typing import Union, get_args, get_origin, overload

from pydantic import TypeAdapter


@overload
def ge(var: str, default: None = None) -> str | None: ...


@overload
def ge[Default](var: str, default: Default) -> str | Default: ...


def ge[Default](var: str, default: Default | None = None) -> str | Default | None:
    """Use the supplied fallback for absent or empty environment values."""
    return os.getenv(var) or default


def _annotation_contains_json_container(target_type: object) -> bool:
    origin = get_origin(target_type)
    if origin in (list, dict):
        return True
    if origin in (UnionType, Union):
        return any(
            arg is not type(None) and _annotation_contains_json_container(arg)
            for arg in get_args(target_type)
        )
    return False


def env_to_pydantic_type(value: object, target_type: object) -> object:
    """Parse a runtime annotation; the owning settings model validates its field.

    An annotation may be a union or parameterized container, not just a class.
    Its result stays unknown to callers until the complete settings model parses it.
    """
    if value is None:
        return None

    origin = get_origin(target_type)
    args = get_args(target_type)
    is_optional = origin in (UnionType, Union) and type(None) in args
    expects_json_container = _annotation_contains_json_container(target_type)

    if isinstance(value, str):
        stripped_value = value.strip()
        if stripped_value == "" and is_optional:
            return None

        if expects_json_container:
            adapter = TypeAdapter[object](target_type)
            return adapter.validate_json(stripped_value)

        value = stripped_value

    adapter = TypeAdapter[object](target_type)
    return adapter.validate_python(value)
