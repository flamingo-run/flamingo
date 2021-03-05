from dataclasses import dataclass, field

from gcp_pilot.datastore import EmbeddedDocument

from models.project import Project


@dataclass
class Network(EmbeddedDocument):
    zone: str
    project: Project = field(default_factory=Project.default_for_network)
