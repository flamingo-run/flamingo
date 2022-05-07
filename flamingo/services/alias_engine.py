import logging
import re
from dataclasses import dataclass, field
from typing import Generator, Any, Tuple

from sanic_rest.exceptions import ValidationError

from models.base import KeyValue

logger = logging.getLogger()

ALIAS_REGEX = r"\${(?P<alias_to>\w+)}"


@dataclass
class ReplacementEngine:
    replacements: KeyValue = field(default_factory=dict)

    def add(self, items: KeyValue):
        for k, v in items.items():
            if AliasEngine.is_virtual(value=v):
                continue
            self.replacements[k] = v

    def get(self, value):
        return self.replacements[value]

    def replace(self, virtual_value):
        aliases_to = re.findall(ALIAS_REGEX, virtual_value)

        new_value = virtual_value
        for alias_to in aliases_to:
            try:
                replace_with = self.replacements[alias_to]
                new_value = new_value.replace(f"${{{alias_to}}}", replace_with)
            except KeyError as e:
                raise ValidationError(f"Could not find the referenced value for {alias_to}") from e

        return new_value


class AliasEngine:
    def __init__(self, items: KeyValue, replacements: ReplacementEngine = None):
        super().__init__()
        self._concrete: KeyValue = {}
        self._virtual: KeyValue = {}

        if not replacements:
            replacements = ReplacementEngine()
            replacements.add(items=items)
        self._replacements = replacements

        self.extend(items)

    @classmethod
    def is_virtual(cls, value):
        matches = re.match(ALIAS_REGEX, str(value))
        return bool(matches)

    def append(self, key: str, value: Any) -> None:
        container = self._virtual if self.is_virtual(value) else self._concrete
        if key in container and value != container[key]:
            logger.warning(f"Duplicate key {key}")
        container[key] = value

    def extend(self, items: KeyValue) -> None:
        for key, value in items.items():
            self.append(key=key, value=value)

    def items(self) -> Generator[Tuple[str, Any], None, None]:
        yield from self._concrete.items()
        for key, virtual_value in self._virtual.items():
            yield key, self._replacements.replace(virtual_value=virtual_value)
