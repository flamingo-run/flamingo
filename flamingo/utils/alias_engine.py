import logging
from typing import Dict, Generator, Any, Tuple

import exceptions

KeyValue = Dict[str, Any]


logger = logging.getLogger()


class AliasEngine:
    def __init__(self, items: KeyValue, replacements: KeyValue = None):
        super().__init__()
        self._concrete: KeyValue = dict()
        self._virtual: KeyValue = dict()
        self._replacements: KeyValue = replacements or items

        self.extend(items)

    def append(self, key: str, value: Any) -> None:
        container = self._virtual if '$' in str(value) else self._concrete
        if key in container and value != container[key]:
            logger.warning(f"Duplicate key {key}")
        container[key] = value

    def extend(self, items: KeyValue) -> None:
        for key, value in items.items():
            self.append(key=key, value=value)

    def items(self) -> Generator[Tuple[str, Any], None, None]:
        yield from self._concrete.items()
        for key, virtual_value in self._virtual.items():
            yield key, self._to_concrete(virtual_value=virtual_value)

    def _to_concrete(self, virtual_value) -> Any:
        alias_to = virtual_value[1:]

        try:
            value = self._replacements[alias_to]
        except KeyError as e:
            raise exceptions.ValidationError(f"Could not find the referenced env var for {virtual_value.as_kv}") from e

        return value
