from __future__ import annotations

import random
import string
from dataclasses import dataclass
from typing import Dict, Any

from gcp_pilot.datastore import EmbeddedDocument


def random_password(length: int) -> str:
    password_characters = string.ascii_letters + string.digits
    return ''.join(random.choice(password_characters) for _ in range(length))


@dataclass
class KeyValueEmbeddedDocument(EmbeddedDocument):
    key: str
    value: str

    @property
    def as_str(self) -> str:
        return f'{self.key}="{self.value}"'

    @property
    def as_kv(self):
        return f'{self.key}={self.value}'


KeyValue = Dict[str, Any]
