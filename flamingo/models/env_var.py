from enum import Enum
from typing import Dict

from models.base import KeyValueEmbeddedDocument

REDACTED = "**********"


class EnvVarSource(Enum):
    USER = "user"
    SHARED = "shared"
    FLAMINGO = "flamingo"


class EnvVar(KeyValueEmbeddedDocument):
    is_secret: bool = False
    source: EnvVarSource = EnvVarSource.USER

    def to_dict(self) -> Dict:
        data = super().to_dict()
        # if self.is_secret:
        #     data['value'] = REDACTED
        return data

    @property
    def is_implicit(self):
        return self.source == EnvVarSource.FLAMINGO
