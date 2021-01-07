from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, TYPE_CHECKING

from gcp_pilot.datastore import Document
from gcp_pilot.storage import GoogleCloudStorage
from slugify import slugify

import settings

if TYPE_CHECKING:
    from models import App  # pylint: disable=ungrouped-imports

KeyValue = Dict[str, str]


@dataclass
class BuildPack(Document):
    name: str
    runtime_version: str
    target: str = 'cloudrun'  # TODO Add support to CloudFunctions and others
    build_args: KeyValue = field(default_factory=dict)
    post_build_commands: List[str] = field(default_factory=list)
    dockerfile_url: str = None

    def __post_init__(self):
        self.name = slugify(self.name)

    @property
    def pk(self) -> str:
        return self.name

    @property
    def tags(self):
        if self.target == 'cloudrun':
            return [
                'gcp-cloud-build-deploy-cloud-run',
                'gcp-cloud-build-deploy-cloud-run-managed',
            ]
        return []

    @property
    def local_dockerfile(self) -> Path:
        return settings.PROJECT_DIR / 'engine' / self.name / 'Dockerfile'

    @property
    def remote_dockerfile(self):
        return f'gs://{settings.FLAMINGO_GCS_BUCKET}/buildpack/{self.name}/Dockerfile'

    async def init(self):
        gcs = GoogleCloudStorage()
        await gcs.create_bucket(
            name=settings.FLAMINGO_GCS_BUCKET,
            region=settings.DEFAULT_REGION,
            project_id=settings.FLAMINGO_PROJECT,
        )

    async def upload_dockerfile(self):
        gcs = GoogleCloudStorage()

        # TODO: invalidate GCS file cache?
        await gcs.upload(
            bucket_name=settings.FLAMINGO_GCS_BUCKET,
            source_file=str(self.local_dockerfile),
            target_file_name=self.remote_dockerfile.replace(f'gs://{settings.FLAMINGO_GCS_BUCKET}/', ''),
            is_public=True,
        )
        return self.remote_dockerfile

    def get_build_args(self, app: App) -> KeyValue:
        all_build_args = {
            'RUNTIME_VERSION': self.runtime_version,
            'APP_PATH': app.path,
        }
        all_build_args.update(**self.build_args)
        return all_build_args

    def get_extra_build_steps(self, app: App) -> List[str]:
        custom_steps = self.post_build_commands
        custom_steps.extend(app.build_setup.post_build_commands)
        return custom_steps
