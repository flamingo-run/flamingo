from enum import Enum

from models.base import KeyValueEmbeddedDocument

REDACTED = "**********"


class EnvVarSource(Enum):
    USER = "user"
    SHARED = "shared"
    FLAMINGO = "flamingo"


class EnvVar(KeyValueEmbeddedDocument):
    is_secret: bool = False
    source: EnvVarSource = EnvVarSource.USER

    @property
    def is_implicit(self):
        return self.source == EnvVarSource.FLAMINGO
