from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, TYPE_CHECKING

from gcp_pilot.datastore import Document
from gcp_pilot.storage import CloudStorage
from slugify import slugify

from models.base import EnvVar
import settings

if TYPE_CHECKING:
    from models import App  # pylint: disable=ungrouped-imports

KeyValue = Dict[str, str]


class Target(Enum):
    CLOUD_RUN = 'cloudrun'
    CLOUD_FUNCTIONS = 'cloud-functions'


@dataclass
class BuildPack(Document):
    name: str
    runtime_version: str
    target: str = Target.CLOUD_RUN.value
    build_args: KeyValue = field(default_factory=dict)
    post_build_commands: List[str] = field(default_factory=list)
    vars: List[EnvVar] = field(default_factory=list)
    dockerfile_url: str = None
    id: str = None

    def __post_init__(self):
        self.name = slugify(self.name)
        self.id = self.name

    @property
    def tags(self):
        if self.target == Target.CLOUD_RUN.value:
            return [
                'gcp-cloud-build-deploy-cloud-run',
                'gcp-cloud-build-deploy-cloud-run-managed',
            ]
        return []

    @property
    def local_dockerfile(self) -> Path:
        return settings.PROJECT_DIR / 'engine' / self.name / 'Dockerfile'

    async def init(self):
        gcs = CloudStorage()
        await gcs.create_bucket(
            name=settings.FLAMINGO_GCS_BUCKET,
            region=settings.FLAMINGO_LOCATION,
            project_id=settings.FLAMINGO_PROJECT,
        )

    async def upload_dockerfile(self):
        gcs = CloudStorage()

        # TODO: invalidate GCS file cache?
        target_file_name = f'buildpack/{self.name}/Dockerfile'
        blob = await gcs.upload(
            bucket_name=settings.FLAMINGO_GCS_BUCKET,
            source_file=str(self.local_dockerfile),
            target_file_name=target_file_name,
            is_public=True,
        )
        return gcs.get_uri(blob)

    def get_build_args(self, app: App) -> KeyValue:
        all_build_args = {
            'RUNTIME_VERSION': self.runtime_version,
            'APP_PATH': app.path,
            'ENVIRONMENT': app.environment_name,
        }
        all_build_args.update(self.build_args)
        return all_build_args

    def get_extra_build_steps(self, app: App) -> List[str]:
        custom_steps = self.post_build_commands.copy()
        custom_steps.extend(app.build_setup.post_build_commands)
        return custom_steps

    def get_all_env_vars(self):
        # Here's the opportunity to inject dynamic env vars from the app's BuildPack
        all_vars = self.vars.copy()
        return all_vars
