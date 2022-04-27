from dataclasses import dataclass
from enum import Enum
from typing import Dict

from models.base import KeyValueEmbeddedDocument

REDACTED = "**********"


class EnvVarSource(Enum):
    USER = "user"
    SHARED = "shared"
    FLAMINGO = "flamingo"


@dataclass
class EnvVar(KeyValueEmbeddedDocument):
    is_secret: bool = False
    source: EnvVarSource = EnvVarSource.USER

    def serialize(self) -> Dict:
        data = super().serialize()
        # if self.is_secret:
        #     data['value'] = REDACTED
        return data

    @property
    def is_implicit(self):
        return self.source == EnvVarSource.FLAMINGO
