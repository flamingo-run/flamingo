from functools import cached_property
from typing import List, Optional, Dict

from gcp_pilot.datastore import EmbeddedDocument
from pydantic import Field
from sanic_rest import exceptions

from models.base import KeyValue
from models.buildpack import BuildPack
from models.label import Label
from models.project import Project


class Build(EmbeddedDocument):
    build_pack_name: str
    trigger_id: str = None
    deploy_branch: str = None
    deploy_tag: str = None
    post_build_commands: List[str] = Field(default_factory=list)
    build_args: KeyValue = Field(default_factory=dict)
    build_machine_type: str = None
    os_dependencies: List[str] = Field(default_factory=list)
    labels: List[Label] = Field(default_factory=list)
    project: Project = None
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
    machine_type: str = None

    def __init__(self, **data):
        super().__init__(**data)

        if not self.deploy_tag and not self.deploy_branch:
            raise exceptions.ValidationError(message="Either deploy_tag or deploy_branch must be provided")
        self.max_instances = max(self.max_instances, 1)

    def to_dict(self) -> Dict:
        data = super().to_dict()
        data.pop("app_id", None)

        data.pop("build_pack_name")
        data["build_pack"] = self.build_pack.to_dict()

        return data

    @cached_property
    def build_pack(self):
        return BuildPack.documents.get(name=self.build_pack_name)

    def get_image_name(self, app: "App", stage: Optional[str] = None) -> str:
        name = app.name
        if stage:
            name = f"{name}--{stage}"
        return f"gcr.io/{app.build.project.id}/{name}:latest"

    def get_labels(self) -> List[Label]:
        all_labels = self.labels.copy()

        # https://cloud.google.com/run/docs/continuous-deployment-with-cloud-build#attach_existing_trigger_to_service
        # Does not seem to work when the trigger and the service deployed are not in the same project
        if self.trigger_id:
            all_labels.extend(
                [
                    Label(key="gcb-trigger-id", value=self.trigger_id),
                    Label(key="commit-sha", value="$COMMIT_SHA"),
                    Label(key="gcb-build-id", value="$BUILD_ID"),
                    Label(key="managed-by", value="gcp-cloud-build-deploy-cloud-run"),
                ]
            )
        return all_labels

    def get_tags(self, app: "App") -> List[str]:
        return self.build_pack.tags + [
            f"{app.name}",
        ]

    def get_build_args(self) -> KeyValue:
        all_build_args = self.build_pack.get_build_args()
        all_build_args.update(
            {
                "OS_DEPENDENCIES": ",".join(self.os_dependencies),
            }
        )
        all_build_args.update(**self.build_args)
        return all_build_args
