from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from gcp_pilot.datastore import Document
from slugify import slugify

from models.env_var import EnvVar, EnvVarSource
from models.network import Network
from models.notification_channel import NotificationChannel
from models.project import Project


@dataclass
class Environment(Document):
    __namespace__ = 'v1'

    name: str
    network: Network = None
    project: Project = field(default_factory=Project.default)
    channel: NotificationChannel = None
    vars: List[EnvVar] = field(default_factory=list)

    def __post_init__(self):
        self.name = slugify(self.name)

    def get_all_env_vars(self) -> List[EnvVar]:
        all_vars = self.vars.copy()
        all_vars.extend([
            EnvVar(key='ENV', value=self.name, source=EnvVarSource.FLAMINGO)
        ])
        return all_vars
