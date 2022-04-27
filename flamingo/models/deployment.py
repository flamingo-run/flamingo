from datetime import datetime
from typing import List, TYPE_CHECKING

from gcp_pilot.datastore import Document, EmbeddedDocument
from pydantic import Field

if TYPE_CHECKING:
    from models.app import App  # pylint: disable=ungrouped-imports


class Source(EmbeddedDocument):
    url: str
    revision: str


class Event(EmbeddedDocument):
    status: str
    source: Source
    created_at: datetime

    @property
    def is_first(self):
        return self.status == "QUEUED"

    @property
    def is_last(self):
        return self.status in ["SUCCESS", "FAILURE", "INTERNAL_ERROR", "TIMEOUT", "CANCELLED", "EXPIRED"]


class Deployment(Document):
    class Config(Document.Config):
        namespace = "v1"

    app_id: str
    build_id: str
    events: List[Event] = Field(default_factory=list)

    async def add_event(self, event: Event, notify: bool = True) -> None:
        self.events.append(event)
        self.save()

        if notify:
            await self.notify()

    @property
    def url(self):
        return f"https://console.cloud.google.com/cloud-build/builds;region=global/{self.build_id}"

    @property
    def app(self) -> "App":
        from models.app import App  # pylint: disable=import-outside-toplevel

        return App.documents.get(id=self.app_id)

    @classmethod
    def merge(cls, app_id: str, build_id: str) -> "Deployment":
        new_deployment = cls(app_id=app_id, build_id=build_id)
        for deployment in cls.documents.filter(build_id=build_id):
            for event in deployment.events:
                new_deployment.add_event(event=event, notify=False)
        return new_deployment

    async def notify(self) -> None:
        app = self.app

        for channel in app.environment.notification_channels:
            engine = channel.build_engine()
            await engine.notify(
                app=app,
                deployment=self,
            )
