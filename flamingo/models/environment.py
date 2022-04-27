from typing import List

from gcp_pilot.datastore import Document
from pydantic import Field
from slugify import slugify

from models.env_var import EnvVar, EnvVarSource
from models.network import Network
from models.notification_channel import NotificationChannel
from models.project import Project


class Environment(Document):
    class Config(Document.Config):
        namespace = "v1"

    name: str
    network: Network = None
    project: Project = Field(default_factory=Project.default)
    notification_channels: List[NotificationChannel] = Field(default_factory=list)
    vars: List[EnvVar] = Field(default_factory=list)

    def __init__(self, **data):
        super().__init__(**data)

        self.name = slugify(self.name)

    def get_all_env_vars(self) -> List[EnvVar]:
        all_vars = []

        for var in self.vars.copy():
            var.source = EnvVarSource.SHARED.value
            all_vars.append(var)

        all_vars.extend([EnvVar(key="ENV", value=self.name, source=EnvVarSource.FLAMINGO)])
        return all_vars
