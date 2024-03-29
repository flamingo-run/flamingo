# pylint: disable=too-many-lines
import logging
from functools import cached_property
from typing import List, Union, TYPE_CHECKING, Optional

from gcp_pilot.datastore import Document, DoesNotExist
from google.api_core.exceptions import FailedPrecondition
from pydantic import Field
from sanic_rest import exceptions
from slugify import slugify

import settings
from models.base import random_password, KeyValue
from models.bucket import Bucket
from models.build import Build
from models.database import Database
from models.env_var import EnvVar, EnvVarSource
from models.environment import Environment
from models.gateway import ApiGateway
from models.label import Label
from models.repository import Repository
from models.schedule import ScheduledInvocation
from models.service_account import ServiceAccount

if TYPE_CHECKING:
    from services.builders import CloudRunFactory, CloudFunctionsFactory  # pylint: disable=ungrouped-imports

logger = logging.getLogger()


class App(Document):
    class Config(Document.Config):
        namespace = "v1"

    name: str
    environment_name: str
    build: Build
    repository: Optional[Repository] = None
    domains: List[str] = Field(default_factory=list)
    vars: List[EnvVar] = Field(default_factory=list)
    scheduled_invocations: List[ScheduledInvocation] = Field(default_factory=list)
    database: Optional[Database] = None
    bucket: Optional[Bucket] = None
    region: Optional[str] = None
    service_account: Optional[ServiceAccount] = None
    endpoint: Optional[str] = None
    integrated_apps: List[str] = Field(default_factory=list)
    gateway: Optional[ApiGateway] = None

    def __init__(self, **data):
        super().__init__(**data)

        _ = self.environment  # check if environment name actually exists, and caches it

        self.name = slugify(self.name)

        if not self.region:
            self.region = self.project.region

        if not self.build.project:
            self.build.project = self.project

    def to_dict(self) -> dict:
        data = super().to_dict()

        data.pop("environment_name")
        data["environment"] = self.environment.to_dict()
        data["build"] = self.build.to_dict()

        if self.service_account:
            data["service_account"].pop("key")
            if self.service_account.json_key:
                data["service_account"]["key_encoded"] = settings.Security.encrypt(self.service_account.json_key)
        return data

    def __str__(self):
        return self.identifier

    @cached_property
    def environment(self) -> Environment:
        return Environment.documents.get(name=self.environment_name)

    @property
    def project(self):
        return self.environment.project

    def set_env_var(self, var: EnvVar):
        self.unset_env_var(key=var.key)
        self.vars.append(var)

    def unset_env_var(self, key: str):
        self.vars = [existing_var for existing_var in self.vars if existing_var.key != key]

    def get_all_env_vars(self) -> List[EnvVar]:
        all_vars = self.vars.copy()

        if self.database:
            all_vars.extend(self.database.as_env)

        if self.bucket:
            all_vars.extend(self.bucket.as_env)

        by_flamingo = EnvVarSource.FLAMINGO.value
        all_vars.extend(
            [
                EnvVar(key="APP_NAME", value=self.name, is_secret=False, source=by_flamingo),
                EnvVar(key="GCP_PROJECT", value=self.project.id, is_secret=False, source=by_flamingo),
                EnvVar(
                    key="GCP_SERVICE_ACCOUNT", value=self.service_account.email, is_secret=False, source=by_flamingo
                ),
                EnvVar(key="GCP_LOCATION", value=self.region, is_secret=False, source=by_flamingo),
            ]
        )

        if self.domains:
            all_vars.extend(
                [
                    EnvVar(key="DOMAIN_URL", value=f"https://{self.domains[0]}", is_secret=False, source=by_flamingo),
                ]
            )

        endpoint = self.get_url()
        all_vars.extend(
            [
                EnvVar(key="GCP_APP_ENDPOINT", value=endpoint, is_secret=False, source=by_flamingo),
            ]
        )

        if self.gateway:
            all_vars.extend(
                [
                    EnvVar(
                        key="GCP_GATEWAY_ENDPOINT",
                        value=self.gateway.gateway_endpoint,
                        is_secret=False,
                        source=by_flamingo,
                    ),
                ]
            )

        for integrated_app in self.integrated_apps:
            try:
                app = App.documents.get(name=integrated_app, environment_name=self.environment_name)
                var_name = f"{app.name.replace('-', '_').upper()}_URL"
                all_vars.extend(
                    [
                        EnvVar(key=var_name, value=app.endpoint, is_secret=False, source=by_flamingo),
                    ]
                )
            except DoesNotExist:
                logger.warning(f"Integrated app {integrated_app} not found in {self.environment_name}")
                continue

        all_vars.extend(self.environment.get_all_env_vars())
        all_vars.extend(self.build.build_pack.get_all_env_vars())

        return all_vars

    def get_all_labels(self) -> List[Label]:
        all_labels = self.build.get_labels()
        all_labels.extend(
            [
                Label(key="service", value=self.name),
            ]
        )
        return all_labels

    def get_all_build_args(self) -> KeyValue:
        return {
            "APP_NAME": self.name,
            "ENV": self.environment_name,
            "APP_DIRECTORY": self.path,
            **self.build.get_build_args(),
        }

    def get_url(self) -> str:
        if not self.endpoint:
            url = self.factory.get_url()
            App.documents.update(pk=self.pk, endpoint=url)
            self.endpoint = url
        return self.endpoint

    def check_env_vars(self):
        self.assure_var(env=EnvVar(key="SECRET", value=random_password(20), is_secret=True))

        all_vars = self.get_all_env_vars()
        implicit_vars = {var.key for var in all_vars if var.is_implicit}
        deduplicated_vars = {}
        for var in all_vars:
            if var.is_implicit:
                continue

            if var.key in implicit_vars or var.key in deduplicated_vars:
                # skip, because it's duplicated
                continue

            deduplicated_vars[var.key] = var

        self.vars = list(deduplicated_vars.values())

    @property
    def path(self) -> str:
        return self.name.replace("-", "_")

    def assure_var(self, env: EnvVar, overwrite: bool = False):
        for var in self.vars:
            if var.key == env.key:
                if overwrite:
                    var.value = env.value
                    var.is_secret = env.is_secret
                return
        self.vars.append(env)

    async def apply(self):
        try:
            trigger_id = await self.factory.build()
        except FailedPrecondition as e:
            raise exceptions.ValidationError(str(e))

        build = self.build

        if trigger_id != build.trigger_id:
            build.trigger_id = trigger_id
            App.documents.update(pk=self.pk, build=build.dict(exclude={"build_pack"}))

            # Since we need the Trigger ID inside the trigger yaml to be used as a CloudRun service label
            # The first time we create the trigger the yaml goes without the label, so we recreate it
            # adding the ID we just received
            return await self.apply()

        return trigger_id

    @property
    def factory(self) -> Union["CloudRunFactory", "CloudFunctionsFactory"]:
        from services.builders import get_factory  # pylint: disable=import-outside-toplevel

        return get_factory(app=self)

    @property
    def identifier(self):
        return f"{self.name}-{self.environment_name}"
