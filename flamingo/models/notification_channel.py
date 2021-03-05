from dataclasses import dataclass, field
from typing import List

from gcp_pilot.datastore import EmbeddedDocument


@dataclass
class NotificationChannel(EmbeddedDocument):
    webhook_url: str
    show_commit_for: List[str] = field(default_factory=lambda: ['SUCCESS'])
