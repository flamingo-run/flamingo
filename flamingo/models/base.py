from __future__ import annotations

import random
import string
from dataclasses import dataclass
from enum import Enum
from typing import Type, Dict

from gcp_pilot.datastore import EmbeddedDocument
from gcp_pilot.resource import ResourceManager, ServiceAgent

import settings


@dataclass
class DoesNotExist(Exception):
    cls: Type[EmbeddedDocument]
    pk: str


def random_password(length: int) -> str:
    password_characters = string.ascii_letters + string.digits
    return ''.join(random.choice(password_characters) for _ in range(length))


@dataclass
class KeyValueEmbeddedDocument(EmbeddedDocument):
    key: str
    value: str

    @property
    def as_str(self) -> str:
        return f'{self.key}="{self.value}"'

    @property
    def as_kv(self):
        return f'{self.key}={self.value}'


@dataclass
class Project(EmbeddedDocument):
    id: str
    number: str = None

    @classmethod
    def default(cls) -> Project:
        return cls(
            id=settings.DEFAULT_PROJECT,
        )

    @classmethod
    def default_for_network(cls) -> Project:
        return cls(
            id=settings.DEFAULT_PROJECT_NETWORK,
        )

    @classmethod
    def default_for_flamingo(cls) -> Project:
        return cls(
            id=settings.FLAMINGO_PROJECT,
        )

    def __post_init__(self):
        if not self.number:
            self.number = ResourceManager().get_project(project_id=self.id)['projectNumber']

    @property
    def compute_account(self) -> str:
        return ServiceAgent.get_compute_service_account(project_id=self.id)

    @property
    def cloud_build_account(self) -> str:
        return ServiceAgent.get_cloud_build_service_account(project_id=self.id)

    @property
    def cloud_run_account(self) -> str:
        return ServiceAgent.get_email(service_name="Google Cloud Run", project_id=self.id)


REDACTED = '**********'


class EnvVarVarSource(Enum):
    USER = 'user'
    FLAMINGO = 'flamingo'
    INHERITED = 'inherited'


@dataclass
class EnvVar(KeyValueEmbeddedDocument):
    is_secret: bool = False
    source: EnvVarVarSource = EnvVarVarSource.USER

    def serialize(self) -> Dict:
        data = super().serialize()
        if self.is_secret:
            data['value'] = REDACTED
        return data

    @property
    def is_implicit(self):
        return self.source != EnvVarVarSource.USER
