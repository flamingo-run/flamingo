from __future__ import annotations

import random
import string
from abc import ABC
from dataclasses import dataclass
from typing import Type, Dict

from gcp_pilot.datastore import EmbeddedDocument
from gcp_pilot.iam import IAM
from gcp_pilot.resource import ResourceManager

import settings


@dataclass
class DoesNotExist(Exception):
    cls: Type[EmbeddedDocument]
    pk: str


def random_password(length: int) -> str:
    password_characters = string.ascii_letters + string.digits
    return ''.join(random.choice(password_characters) for _ in range(length))


@dataclass
class KeyValueEmbeddedDocument(EmbeddedDocument, ABC):
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
            project_info = ResourceManager().get_project(project_id=self.id)
            self.number = project_info['projectNumber']

    @property
    def compute_account(self) -> str:
        return IAM().get_compute_service_account(project_number=self.number)

    @property
    def cloud_build_account(self) -> str:
        return IAM().get_cloud_build_service_account(project_number=self.number)

    @property
    def cloud_run_account(self) -> str:
        return IAM().get_cloud_run_service_account(project_number=self.number)


REDACTED = '**********'


@dataclass
class EnvVar(KeyValueEmbeddedDocument):
    is_secret: bool = False

    def serialize(self) -> Dict:
        data = super().serialize()
        if self.is_secret:
            data['value'] = REDACTED
        return data
