from dataclasses import dataclass

import settings
from models.app import App
from models.base import random_password
from models.bucket import Bucket
from models.database import Database
from models.repository import Repository
from models.service_account import ServiceAccount


@dataclass
class AppBootstrap:
    app: App

    def check(self):
        changes = {}
        if not self.app.database:
            changes['database'] = self.database()

        if not self.app.bucket:
            changes['bucket'] = self.bucket

        if not self.app.service_account:
            changes['service_account'] = self.service_account

        if not self.repository:
            changes['repository'] = self.repository

        if not self.app.domains:
            changes['domains'] = self.domains

        return changes

    def apply(self):
        changes = self.check()
        for field, value in changes.items():
            setattr(self.app, field, value)
        return self.app.save()

    @property
    def bucket(self) -> Bucket:
        return Bucket(
            name=self.app.name,
            project=self.app.project,
            region=self.app.region,
        )

    def database(self) -> Database:
        return Database(
            instance=self.app.name,
            name=self.app.path,
            user=f'app.{self.app.path}',
            password=random_password(20),
            project=self.app.project,
        )

    @property
    def repository(self) -> Repository:
        return Repository(
            name=self.app.name,
        )

    @property
    def service_account(self) -> ServiceAccount:
        all_roles = ([settings.DEFAULT_ROLE] if settings.DEFAULT_ROLE else []) + [
            # TODO Handle other types
            'run.invoker',  # allow authenticated integrations such as PubSub, Cloud Scheduler
        ]
        return ServiceAccount(
            name=self.app.name,
            display_name=self.app.name,
            description=f"{self.app.name} Service Account",
            roles=all_roles,
            project=self.app.project,
        )

    @property
    def domains(self):
        if self.app.environment.network:
            return [
                f'{self.app.name}.{self.app.environment.name}.{self.app.environment.network.zone}',
            ]
        return []
