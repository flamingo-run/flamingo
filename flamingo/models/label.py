from dataclasses import dataclass

from models.base import KeyValueEmbeddedDocument


@dataclass
class Label(KeyValueEmbeddedDocument):
    pass
