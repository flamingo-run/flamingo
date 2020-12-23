from __future__ import annotations

from dataclasses import dataclass, field
# Avoid cyclic import
from typing import TYPE_CHECKING, List

from models.base import Document, Project, EmbeddedDocument, EnvVar

if TYPE_CHECKING:
    pass


@dataclass
class Network(EmbeddedDocument):
    zone: str
    project: Project = field(default_factory=Project.default_for_network)


@dataclass
class NotificationChannel(EmbeddedDocument):
    webhook_url: str

    async def make_deploy_payload(self, app_name: str) -> dict:
        return {
            'text': f'🚀 The service **{app_name}** has just been deployed!'
        }


@dataclass
class Environment(Document):
    name: str
    network: Network = None
    project: Project = field(default_factory=Project.default)
    channel: NotificationChannel = None
    vars: List[EnvVar] = field(default_factory=list)

    @property
    def pk(self) -> str:
        return self.name
