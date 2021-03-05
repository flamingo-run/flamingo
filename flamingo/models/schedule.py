from dataclasses import dataclass

from gcp_pilot.datastore import EmbeddedDocument


@dataclass
class ScheduledInvocation(EmbeddedDocument):
    name: str
    cron: str
    path: str = '/'
    method: str = 'GET'
    body: str = None
    cloud_scheduler_id: str = None
    content_type: str = 'application/json'
