from gcp_pilot.datastore import EmbeddedDocument


class ScheduledInvocation(EmbeddedDocument):
    name: str
    cron: str
    path: str = "/"
    method: str = "GET"
    body: str = None
    cloud_scheduler_id: str = None
    content_type: str = "application/json"
