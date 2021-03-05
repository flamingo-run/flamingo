from dataclasses import dataclass, field
from typing import List
from urllib.parse import urlparse

from gcp_pilot.datastore import EmbeddedDocument

import settings
from models.env_var import EnvVar, EnvVarSource
from models.project import Project


@dataclass
class Database(EmbeddedDocument):
    instance: str
    name: str
    user: str
    password: str
    version: str = settings.DEFAULT_DB_VERSION
    tier: str = settings.DEFAULT_DB_TIER
    region: str = None
    project: Project = field(default_factory=Project.default)
    env_var: str = 'DATABASE_URL'
    high_availability: bool = False

    def __post_init__(self):
        if not self.user:
            self.user = f'app.{self.name}'
        if not self.region:
            self.region = self.project.region

    @property
    def engine(self) -> str:
        return self.version.split('_')[0].lower()

    @property
    def url(self) -> str:
        auth = f"{self.user}:{self.password}"
        url = f"//cloudsql/{self.connection_name}"
        return f"{self.engine}://{auth}@{url}/{self.name}"

    @property
    def connection_name(self) -> str:
        return f"{self.project.id}:{self.region}:{self.instance}"

    @property
    def as_env(self) -> List[EnvVar]:
        by_flamingo = EnvVarSource.FLAMINGO.value
        if '*' in self.env_var:
            prefix = self.env_var.replace('*', '')
            parts = urlparse(self.url)
            if parts.path.startswith('//'):  # CloudSQL socket
                instance, name = parts.path.rsplit('/', 1)
                instance = instance.replace('//', '/')
            else:
                instance, name = parts.hostname, parts.path.replace('/', '')
            db_envs = [
                EnvVar(key=f'{prefix}ENGINE', value=parts.scheme, is_secret=False, source=by_flamingo),
                EnvVar(key=f'{prefix}HOST', value=instance, is_secret=False, source=by_flamingo),
                EnvVar(key=f'{prefix}SCHEMA', value=name, is_secret=False, source=by_flamingo),
                EnvVar(key=f'{prefix}USERNAME', value=parts.username, is_secret=False, source=by_flamingo),
                EnvVar(key=f'{prefix}PASSWORD', value=parts.password, is_secret=True, source=by_flamingo),
            ]
        else:
            db_envs = [EnvVar(key=self.env_var, value=self.url, is_secret=True, source=by_flamingo)]
        return db_envs
