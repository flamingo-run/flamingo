from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, TYPE_CHECKING

from gcp_pilot.datastore import Document
from gcp_pilot.storage import CloudStorage
from google.api_core.exceptions import NotFound
from slugify import slugify

import settings
from models.base import KeyValue
from models.env_var import EnvVar, EnvVarSource

if TYPE_CHECKING:
    from models.app import App


class Target(Enum):
    CLOUD_RUN = 'cloud-run'
    CLOUD_FUNCTIONS = 'cloud-functions'


@dataclass
class BuildPack(Document):
    __namespace__ = 'v1'

    name: str
    runtime: str
    target: str = Target.CLOUD_RUN.value
    build_args: KeyValue = field(default_factory=dict)
    post_build_commands: List[str] = field(default_factory=list)
    env_vars: List[EnvVar] = field(default_factory=list)
    dockerfile_url: str = None

    def __post_init__(self):
        self.name = slugify(self.name)

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

    async def upload_dockerfile(self):
        target_file_name = f'buildpack/{self.name}/Dockerfile'

        gcs = CloudStorage()

        # versioning
        try:
            timestamp = int(datetime.now().timestamp())
            await gcs.copy(
                source_file_name=target_file_name,
                target_file_name=f"{target_file_name}.{timestamp}",
                source_bucket_name=settings.FLAMINGO_GCS_BUCKET,
                target_bucket_name=settings.FLAMINGO_GCS_BUCKET,
            )
        except NotFound:
            pass

        # TODO: invalidate GCS file cache?
        blob = await gcs.upload(
            bucket_name=settings.FLAMINGO_GCS_BUCKET,
            source_file=str(self.local_dockerfile),
            target_file_name=target_file_name,
            is_public=True,
        )
        return gcs.get_uri(blob)

    def get_build_args(self) -> KeyValue:
        all_build_args = {
            'RUNTIME': self.runtime,
        }
        all_build_args.update(self.build_args)
        return all_build_args

    def get_extra_build_steps(self, app: 'App') -> List[str]:
        custom_steps = self.post_build_commands.copy()
        custom_steps.extend(app.build.post_build_commands)
        return custom_steps

    def get_all_env_vars(self):
        # Here's the opportunity to inject dynamic env vars from the app's BuildPack
        all_vars = []

        for var in self.env_vars.copy():
            var.source = EnvVarSource.SHARED.value
            all_vars.append(var)

        return all_vars
