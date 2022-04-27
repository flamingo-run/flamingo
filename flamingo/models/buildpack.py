from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, TYPE_CHECKING

from gcp_pilot.datastore import Document
from gcp_pilot.storage import CloudStorage
from google.api_core.exceptions import NotFound
from pydantic import Field
from slugify import slugify

import settings
from models.base import KeyValue
from models.env_var import EnvVar, EnvVarSource

if TYPE_CHECKING:
    from models.app import App


class Target(Enum):
    CLOUD_RUN = "cloud-run"
    CLOUD_FUNCTIONS = "cloud-functions"


class BuildPack(Document):
    class Config(Document.Config):
        namespace = "v1"

    name: str
    runtime: str
    target: str = Target.CLOUD_RUN.value
    build_args: KeyValue = Field(default_factory=dict)
    post_build_commands: List[str] = Field(default_factory=list)
    env_vars: List[EnvVar] = Field(default_factory=list)
    dockerfile_url: str = None
    dockerfile_stages: List[str] = Field(default_factory=list)

    def __init__(self, **data):
        super().__init__(**data)

        self.name = slugify(self.name)
        self._extract_dockerfile_stages()

    def _extract_dockerfile_stages(self):
        if not self.dockerfile_url:
            return

        storage = CloudStorage()
        blob = storage.get_file(uri=self.dockerfile_url)
        content = blob.download_as_text()

        image_names = []
        for row in content.splitlines():
            if not row.startswith("FROM"):
                continue

            if " as " not in row.lower():
                image_names.append("")  # the whole dockerfile image
            else:
                _, image_name = row.replace(" AS ", " as ").split(" as ")
                image_names.append(image_name.strip())

        self.dockerfile_stages = image_names

    @property
    def tags(self):
        if self.target == Target.CLOUD_RUN.value:
            return [
                "gcp-cloud-build-deploy-cloud-run",
                "gcp-cloud-build-deploy-cloud-run-managed",
            ]
        return []

    @property
    def local_dockerfile(self) -> Path:
        return settings.PROJECT_DIR / "engine" / self.name / "Dockerfile"

    async def upload_dockerfile(self):
        target_file_name = f"buildpack/{self.name}/Dockerfile"

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
            "RUNTIME": self.runtime,
        }
        all_build_args.update(self.build_args)
        return all_build_args

    def get_extra_build_steps(self, app: "App") -> List[str]:
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
