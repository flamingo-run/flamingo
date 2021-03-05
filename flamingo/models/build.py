from dataclasses import dataclass, field
from typing import List

from gcp_pilot.datastore import EmbeddedDocument

import exceptions
import settings
from models.buildpack import BuildPack
from models.label import Label
from models.project import Project


@dataclass
class Build(EmbeddedDocument):
    build_pack_name: str
    trigger_id: str = None
    deploy_branch: str = None
    deploy_tag: str = None
    post_build_commands: List[str] = field(default_factory=list)
    os_dependencies: List[str] = field(default_factory=list)
    labels: List[Label] = field(default_factory=list)
    project: Project = field(default_factory=Project.default_for_flamingo)
    memory: int = 256  # measured in MB
    cpu: int = 1  # number of cores
    min_instances: int = 0
    max_instances: int = 10
    timeout: int = 60 * 15  # TODO: timeout above 15m is still beta on CloudRun
    concurrency: int = 80
    is_authenticated: bool = True
    entrypoint: str = None
    directory: str = None
    build_timeout: int = 60 * 30  # <https://cloud.google.com/cloud-build/docs/build-config#timeout_2>

    _build_pack: BuildPack = None

    def __post_init__(self):
        if not self.deploy_tag and not self.deploy_branch:
            raise exceptions.ValidationError(message="Either deploy_tag or deploy_branch must be provided")
        if self.max_instances < 1:
            self.max_instances = 1

    def serialize(self) -> dict:
        data = super().serialize()
        data.pop('app_id')

        data.pop('build_pack_name')
        data['build_pack'] = self.build_pack.serialize()

        return data

    @property
    def build_pack(self):
        if not self._build_pack:
            self._build_pack = BuildPack.documents.get(id=self.build_pack_name)
        return self._build_pack

    def get_image_name(self, app: 'App') -> str:
        return f"gcr.io/{settings.FLAMINGO_PROJECT}/{app.identifier}:latest"

    def get_labels(self) -> List[Label]:
        all_labels = self.labels.copy()

        # https://cloud.google.com/run/docs/continuous-deployment-with-cloud-build#attach_existing_trigger_to_service
        # Does not seem to work when the trigger and the service deployed are not in the same project
        if self.trigger_id:
            all_labels.append(
                Label(key='gcb-trigger-id', value=self.trigger_id)
            )
        return all_labels

    def get_tags(self, app: 'App') -> List[str]:
        return self.build_pack.tags + [
            f'{app.name}',
        ]
