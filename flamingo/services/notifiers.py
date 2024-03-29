from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List

from gcp_pilot.chats import ChatsHook, Card, Section

import settings
from services.new_relic import NewRelicAPI

if TYPE_CHECKING:
    from models.app import App
    from models.deployment import Deployment


@dataclass
class ChatNotifier:
    webhook_url: str
    show_commit_for: List[str] = field(default_factory=lambda: ["SUCCESS"])

    async def notify(self, deployment: "Deployment", app: "App") -> Dict:
        chat = ChatsHook(hook_url=self.webhook_url)
        card = self._build_message_card(deployment=deployment, app=app)
        return chat.send_card(card=card, thread_key=f"flamingo_{deployment.build_id}")

    def _build_message_card(self, deployment: "Deployment", app: "App") -> Card:
        current_event = deployment.events[-1]
        try:
            previous_event = deployment.events[-2]
        except IndexError:
            previous_event = None

        status = current_event.status

        card = Card()
        card.add_header(
            title=f"{app.name}", subtitle=f"{self._get_action(status=status)} <b>{app.environment_name.upper()}</b>"
        )

        section = Section()
        # TODO: Fix image too big
        # section.add_image(image_url=self._get_icon(status=status))

        if current_event.is_first:
            section.add_button(
                url=deployment.url,
                text="DETAILS",
            )

        if current_event.is_last:
            first_event = deployment.events[0]
            duration = current_event.created_at - first_event.created_at
            section.add_text(
                title="Duration",
                content=str(duration),
            )

        if previous_event and status in self.show_commit_for:
            commits = app.repository.get_commit_diff(
                current_revision=current_event.source.revision,
                previous_revision=previous_event.source.revision,
            )
            if commits:
                diff_messages = []
                for sha, author, msg in commits:
                    diff_messages.append(f"{sha} @{author}\n\t{msg}")
                diff_message = "\n".join(diff_messages)
            else:
                diff_message = (
                    f"No changes detected between <i>{current_event.source.revision}</i> "
                    f"and <i>{previous_event.source.revision}</i>"
                )
            section.add_text(
                title="Changes",
                content=f"{diff_message}",
            )

        card.add_section(section=section)
        return card

    @classmethod
    def _get_action(cls, status: str) -> str:
        # https://cloud.google.com/cloud-build/docs/api/reference/rest/v1/projects.builds#status
        return (
            {
                "STATUS_UNKNOWN": "???",
                "QUEUED": "is about to be deployed to",
                "WORKING": "is deploying to",
                "SUCCESS": "has been deployed to",
                "FAILURE": "failed to deploy to",
                "INTERNAL_ERROR": "crashed when deploying to",
                "TIMEOUT": "took too long to deploy to",
                "CANCELLED": "has been cancelled to deploy to",
                "EXPIRED": "took too long to start deployment to",
            }
            .get(status)
            .upper()
        )

    @classmethod
    def _get_icon(cls, status: str) -> str:
        # https://cloud.google.com/cloud-build/docs/api/reference/rest/v1/projects.builds#status
        icon_name = f"deploy_{status.lower()}.png"
        return f"https://storage.googleapis.com/{settings.FLAMINGO_GCS_BUCKET}/media/{icon_name}"


@dataclass
class NewRelicNotifier:
    api_key: str

    async def notify(self, deployment: "Deployment", app: "App") -> Dict:
        api = NewRelicAPI(api_key=self.api_key)
        api.notify_deployment(
            app_name=app.identifier,
            revision=deployment.build_id,
            # user=''  # TODO get user
        )
