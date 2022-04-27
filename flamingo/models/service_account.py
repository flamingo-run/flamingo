import base64
from dataclasses import dataclass, field
from typing import List, ClassVar, Optional

from gcp_pilot.datastore import EmbeddedDocument
from gcp_pilot.iam import IdentityAccessManager

from models.project import Project


@dataclass
class ServiceAccount(EmbeddedDocument):
    name: str
    description: str = ""
    display_name: str = ""
    roles: List[str] = field(default_factory=list)
    project: Project = field(default_factory=Project.default)
    key: Optional[str] = None

    _exclude_from_indexes: ClassVar = ("key",)

    @property
    def email(self) -> str:
        return f"{self.name}@{self.project.id}.iam.gserviceaccount.com"

    def get_all_roles(self):
        return self.roles + ["run.admin"]

    def rotate_key(self):
        iam = IdentityAccessManager(project_id=self.project.id)
        for key_data in iam.list_keys(service_account_name=self.name):
            if key_data["keyType"] == "USER_MANAGED":
                iam.delete_key(key_id=key_data["id"], service_account_name=self.name)
        key_data = iam.create_key(service_account_name=self.name)
        self.key = key_data["privateKeyData"]

    @property
    def json_key(self) -> Optional[str]:
        return base64.b64decode(self.key).decode() if self.key else None
