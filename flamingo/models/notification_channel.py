from dataclasses import dataclass
from enum import Enum
from typing import Dict, Union, Any

from gcp_pilot.datastore import EmbeddedDocument
from sanic_rest.exceptions import ValidationError

from services.notifiers import ChatNotifier, NewRelicNotifier


class NotificationEngine(Enum):
    GOOGLE_CHAT = 'google-chat'
    NEW_RELIC = 'new-relic'

    @classmethod
    def get_engine_class(cls, name):
        if name == cls.GOOGLE_CHAT.value:
            return ChatNotifier
        if name == cls.NEW_RELIC.value:
            return NewRelicNotifier
        raise NotImplementedError(f"Unsupported notification engine {name}")


@dataclass
class NotificationChannel(EmbeddedDocument):
    engine: str
    config: Dict[str, Any]

    def __post_init__(self):
        # light validation
        try:
            self.build_engine()
        except TypeError as e:
            raise ValidationError(str(e)) from e

    def build_engine(self) -> Union[ChatNotifier, NewRelicNotifier]:
        klass = NotificationEngine.get_engine_class(name=self.engine)
        return klass(**self.config)
