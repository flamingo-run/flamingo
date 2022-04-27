from gcp_pilot.datastore import EmbeddedDocument
from pydantic import Field

from models.project import Project


class Network(EmbeddedDocument):
    zone: str
    zone_name: str = None
    project: Project = Field(default_factory=Project.default_for_network)
    vpc_connector: str = None

    def __init__(self, **data):
        super().__init__(**data)

        if not self.zone_name:
            self.zone_name = self.zone.strip(".").replace(".", "-")

    def get_record_name(self, domain):
        return f"{domain}.{self.zone}"
