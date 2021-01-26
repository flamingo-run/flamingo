from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from gcp_pilot.datastore import Document, EmbeddedDocument

from models import App


@dataclass
class Source(EmbeddedDocument):
    url: str
    revision: str


@dataclass
class Event(EmbeddedDocument):
    status: str
    source: Source
    created_at: datetime


@dataclass
class Deployment(Document):
    app_id: str
    build_id: str
    events: List[Event] = field(default_factory=list)

    async def add_event(self, event: Event, notify: bool = True) -> None:
        self.events.append(event)
        self.save()

        if notify:
            await self.app.environment.channel.notify(
                deployment=self,
                app=self.app,
            )

    @property
    def app(self):
        return App.documents.get(id=self.app_id)
