from gcp_pilot.datastore import EmbeddedDocument


class ApiGateway(EmbeddedDocument):
    api_name: str
    spec_path: str = "./openapi.yaml.jinja"
    gateway_id: str = None
    gateway_endpoint: str = None
    gateway_service: str = None
    cors_enabled: bool = True

    def __init__(self, **data):
        super().__init__(**data)

        if not self.gateway_id:
            self.gateway_id = self.api_name
