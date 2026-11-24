"""Objects returned by the API."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Mapping, Type, TypeVar

__all__ = ["LeadveyorObject"]

_T = TypeVar("_T", bound="LeadveyorObject")

#: Model classes by name, filled as the generated models are defined (for the string references in ``_types``).
_REGISTRY: Dict[str, Type["LeadveyorObject"]] = {}


class LeadveyorObject(Dict[str, Any]):
    """An object returned by the API: a ``dict`` whose fields can also be read as attributes.

    .. code-block:: python

        lead.evaluation.tier
        lead["evaluation"]["tier"]
        lead.to_dict()      # plain dicts all the way down
        json.dumps(lead)    # it is a dict, so this just works

    Typed subclasses live in ``leadveyor.models`` (Lead, Inbound, Profile…). A field the model declares but the
    response leaves out reads as None; an unknown attribute raises AttributeError.
    """

    #: Fields that convert to a model: ``{"evaluation": "Evaluation", "leads": ["Lead"]}``. Set by generated models.
    _types: ClassVar[Mapping[str, Any]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _REGISTRY[cls.__name__] = cls

    @classmethod
    def construct_from(cls: Type[_T], data: Mapping[str, Any]) -> _T:
        """Builds the object (and its typed children) from decoded JSON."""
        obj = cls()
        for key, value in data.items():
            spec = cls._types.get(key)
            if isinstance(spec, str) and isinstance(value, dict):
                dict.__setitem__(obj, key, _REGISTRY[spec].construct_from(value))
            elif isinstance(spec, list) and isinstance(value, list):
                item_cls = _REGISTRY[spec[0]]
                dict.__setitem__(obj, key, [item_cls.construct_from(v) if isinstance(v, dict) else convert(v) for v in value])
            else:
                dict.__setitem__(obj, key, convert(value))
        return obj

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError:
            if name in _declared_fields(type(self)):
                return None
            raise AttributeError(f"{type(self).__name__!r} object has no field {name!r}") from None

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name) from None

    def to_dict(self) -> Dict[str, Any]:
        """The object as plain dicts and lists, all the way down."""
        return {k: _plain(v) for k, v in self.items()}

    def __repr__(self) -> str:
        return f"{type(self).__name__}({dict.__repr__(self)})"

    # dict.copy() would return a plain dict
    def copy(self: _T) -> _T:
        return type(self).construct_from(self.to_dict())


def _declared_fields(cls: type) -> set[str]:
    fields: set[str] = set()
    for klass in cls.__mro__:
        fields.update(getattr(klass, "__annotations__", {}).keys())
    return fields


def convert(value: Any) -> Any:
    """Decoded JSON → LeadveyorObject for objects, lists of those for arrays, scalars as they are."""
    if isinstance(value, dict) and not isinstance(value, LeadveyorObject):
        return LeadveyorObject.construct_from(value)
    if isinstance(value, list):
        return [convert(v) for v in value]
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, LeadveyorObject):
        return value.to_dict()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value
