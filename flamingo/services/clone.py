from dataclasses import dataclass
from typing import Optional

from gcp_pilot.datastore import DoesNotExist
from sanic_rest.exceptions import NotFoundError, ValidationError

from models.app import App
from models.environment import Environment
from models.network import Network
from models.project import Project


@dataclass
class AppClone:
    app: App

    def clone(self, env_id: str) -> App:
        if not env_id:
            raise ValidationError("environment_id is required")

        if int(env_id) == self.app.environment.id:
            raise ValidationError("destination environment cannot be the same as source")

        try:
            environment = Environment.documents.get(id=env_id)
        except DoesNotExist as exc:
            raise NotFoundError("destination environment not found") from exc

        clone_app = App.from_entity(self.app.to_entity())

        clone_app.id = None
        clone_app.environment_name = environment.name
        clone_app.build.project = environment.project
        clone_app.repository.project = environment.project
        clone_app.vars = self.app.vars

        clone_app.domains = []
        clone_app.database = None
        clone_app.bucket = None
        clone_app.service_account = None
        clone_app.endpoint = None
        clone_app.gateway = None

        return clone_app.save()


@dataclass
class EnvironmentClone:
    environment: Environment

    def clone(
        self,
        env_name: Optional[str] = None,
        project_id: Optional[str] = None,
        zone: Optional[str] = None,
        vpc_connector: Optional[str] = None,
    ) -> Environment:
        if not env_name:
            raise ValidationError("environment_name is required")
        if not project_id:
            raise ValidationError("project_id is required")
        if not zone:
            raise ValidationError("zone is required")

        clone_env = Environment.from_entity(self.environment.to_entity())

        clone_env.id = None
        clone_env.name = env_name

        project = Project(id=project_id)
        clone_env.network = Network(zone=zone, project=project, vpc_connector=vpc_connector)
        clone_env.project = project

        return clone_env.save()
