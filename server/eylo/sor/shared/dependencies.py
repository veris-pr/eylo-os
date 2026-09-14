"""Pure validation and ordering for code-owned SOR stream dependency graphs."""

from __future__ import annotations

from collections.abc import Mapping


def validate_stream_dependencies(
    dependencies: Mapping[str, frozenset[str]],
) -> None:
    """Reject missing nodes, self-dependencies, and cycles at registration time."""
    keys = frozenset(dependencies)
    for stream_key, required in dependencies.items():
        if stream_key in required:
            raise ValueError(f"SOR stream {stream_key} cannot depend on itself.")
        unknown = required - keys
        if unknown:
            raise ValueError(
                f"SOR stream {stream_key} depends on unknown streams: "
                f"{sorted(unknown)}."
            )
    topological_stream_layers(dependencies)


def topological_stream_layers(
    dependencies: Mapping[str, frozenset[str]],
) -> tuple[tuple[str, ...], ...]:
    """Return deterministic parallel layers or reject a cyclic graph."""
    remaining = {key: set(required) for key, required in dependencies.items()}
    layers: list[tuple[str, ...]] = []
    resolved: set[str] = set()
    while remaining:
        ready = tuple(
            sorted(
                key
                for key, required in remaining.items()
                if required.issubset(resolved)
            )
        )
        if not ready:
            cycle_nodes = ", ".join(sorted(remaining))
            raise ValueError(
                f"SOR stream dependency graph contains a cycle: {cycle_nodes}."
            )
        layers.append(ready)
        resolved.update(ready)
        for key in ready:
            remaining.pop(key)
    return tuple(layers)


def selected_stream_dependencies(
    dependencies: Mapping[str, frozenset[str]],
    selected: frozenset[str],
) -> dict[str, frozenset[str]]:
    """Keep ordering only within explicitly selected source objects."""
    return {
        key: frozenset(required & selected)
        for key, required in dependencies.items()
        if key in selected
    }


__all__ = [
    "selected_stream_dependencies",
    "topological_stream_layers",
    "validate_stream_dependencies",
]
