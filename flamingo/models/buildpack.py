from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, TYPE_CHECKING

from gcp_pilot.datastore import Document
from gcp_pilot.storage import CloudStorage
from slugify import slugify

from models.base import EnvVar
import exceptions
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
    vars: List[EnvVar] = field(default_factory=list)
    dockerfile_url: str = None
    id: str = None

    def __post_init__(self):
        self.name = slugify(self.name)
        self.id = self.name

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

    async def get_build_args(self, app: App) -> KeyValue:
        all_build_args = {
            'RUNTIME_VERSION': self.runtime_version,
            'APP_PATH': app.path,
            'ENVIRONMENT': app.environment_name,
        }

        # dynamically create build args from env vars
        all_env_vars = await app.get_all_env_vars()

        def _find_env_var(k):
            for env_var in all_env_vars:
                if env_var.key == k:
                    return env_var.value
            raise exceptions.ValidationError(f"Dynamic Build Argument {k} could not be filled from env variables")

        for key, value in self.build_args.items():
            if key.startswith('$'):
                value = _find_env_var(key.replace('$', ''))
            all_build_args[key] = value

        return all_build_args

    def get_extra_build_steps(self, app: App) -> List[str]:
        custom_steps = self.post_build_commands
        custom_steps.extend(app.build_setup.post_build_commands)
        return custom_steps

    def get_all_env_vars(self):
        # Here's the opportunity to inject dynamic env vars from the app's BuildPack
        return self.vars
