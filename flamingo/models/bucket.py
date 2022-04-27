from typing import List

from gcp_pilot.datastore import EmbeddedDocument
from pydantic import Field

from models.env_var import EnvVar, EnvVarSource
from models.project import Project


class Bucket(EmbeddedDocument):
    name: str
    env_var: str = "GCS_BUCKET"
    region: str = None
    project: Project = Field(default_factory=Project.default)

    def __init__(self, **data):
        super().__init__(**data)

        if not self.region:
            self.region = self.project.region

    @property
    def url(self):
        return f"gs://{self.name}"

    @property
    def as_env(self) -> List[EnvVar]:
        return [
            EnvVar(
                key=self.env_var,
                value=self.name,
                is_secret=False,
                source=EnvVarSource.FLAMINGO.value,
            )
        ]
