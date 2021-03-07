from dataclasses import field, dataclass
from typing import List

from gcp_pilot.datastore import EmbeddedDocument

from models.env_var import EnvVar, EnvVarSource
from models.project import Project


@dataclass
class Bucket(EmbeddedDocument):
    name: str
    env_var: str = 'GCS_BUCKET_NAME'
    region: str = None
    project: Project = field(default_factory=Project.default)

    def __post_init__(self):
        if not self.region:
            self.region = self.project.region

    @property
    def url(self):
        return f'gs://{self.name}'

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
