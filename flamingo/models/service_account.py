from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from gcp_pilot.datastore import EmbeddedDocument

from models.project import Project


@dataclass
class ServiceAccount(EmbeddedDocument):
    name: str
    description: str
    display_name: str
    roles: List[str] = field(default_factory=list)
    project: Project = field(default_factory=Project.default)

    @property
    def email(self) -> str:
        return f'{self.name}@{self.project.id}.iam.gserviceaccount.com'
