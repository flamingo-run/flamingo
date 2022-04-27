from dataclasses import dataclass, field

from gcp_pilot.datastore import EmbeddedDocument

from models.project import Project


@dataclass
class Network(EmbeddedDocument):
    zone: str
    zone_name: str = None
    project: Project = field(default_factory=Project.default_for_network)
    vpc_connector: str = None

    def __post_init__(self):
        if not self.zone_name:
            self.zone_name = self.zone.strip(".").replace(".", "-")

    def get_record_name(self, domain):
        return f"{domain}.{self.zone}"
