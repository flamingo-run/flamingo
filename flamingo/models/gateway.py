from dataclasses import dataclass

from gcp_pilot.datastore import EmbeddedDocument


@dataclass
class ApiGateway(EmbeddedDocument):
    api_name: str
    spec_path: str = "./openapi.yaml"
    gateway_id: str = None
    gateway_endpoint: str = None

    def __post_init__(self):
        if not self.gateway_id:
            self.gateway_id = self.api_name
