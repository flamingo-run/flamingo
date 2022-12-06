from dataclasses import dataclass

from gcp_pilot.datastore import DoesNotExist
from sanic_rest.exceptions import NotFoundError, ValidationError

from models.app import App
from models.environment import Environment


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
