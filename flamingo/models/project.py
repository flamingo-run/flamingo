from dataclasses import dataclass

from gcp_pilot.datastore import EmbeddedDocument
from gcp_pilot.resource import ResourceManager, ServiceAgent

import settings


@dataclass
class Project(EmbeddedDocument):
    id: str
    number: str = None
    region: str = None  # Project's have default region, as defined by AppEngine API

    def __post_init__(self):
        if not self.number or not self.region:
            rm = ResourceManager(project_id=self.id)
            self.number = self.number or rm.get_project(project_id=self.id)["projectNumber"]
            self.region = self.region or rm.location

    @property
    def compute_account(self) -> str:
        return ServiceAgent.get_compute_service_account(project_id=self.id)

    @property
    def cloud_build_account(self) -> str:
        return ServiceAgent.get_cloud_build_service_account(project_id=self.id)

    @property
    def cloud_run_account(self) -> str:
        return ServiceAgent.get_email(service_name="Google Cloud Run", project_id=self.id)

    @property
    def pubsub_account(self) -> str:
        return ServiceAgent.get_email(service_name="Cloud Pub/Sub", project_id=self.id)

    @property
    def tasks_account(self) -> str:
        return ServiceAgent.get_email(service_name="Cloud Tasks", project_id=self.id)

    @property
    def scheduler_account(self) -> str:
        return ServiceAgent.get_email(service_name="Cloud Scheduler", project_id=self.id)

    @classmethod
    def default(cls) -> "Project":
        return Project(
            id=settings.DEFAULT_PROJECT,
        )

    @classmethod
    def default_for_network(cls) -> "Project":
        return Project(
            id=settings.DEFAULT_PROJECT_NETWORK,
        )

    @classmethod
    def default_for_flamingo(cls) -> "Project":
        return Project(
            id=settings.FLAMINGO_PROJECT,
        )
