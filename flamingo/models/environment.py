from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, TYPE_CHECKING, Dict, Tuple

from gcp_pilot.build import CloudBuild
from gcp_pilot.datastore import Document, EmbeddedDocument
from gcp_pilot.chats import ChatsHook, Card, Text, Section
from github import Github
from slugify import slugify

from models.base import Project, EnvVar

if TYPE_CHECKING:
    from models import App, Repository  # pylint: disable=ungrouped-imports


@dataclass
class Network(EmbeddedDocument):
    zone: str
    project: Project = field(default_factory=Project.default_for_network)


@dataclass
class NotificationChannel(EmbeddedDocument):
    webhook_url: str
    detect_commit_diff: bool = False

    async def notify(self, build_data: Dict, app: App) -> Dict:
        chat = ChatsHook(hook_url=self.webhook_url)
        card = self._build_message_card(build_data=build_data, app=app)
        return chat.send_card(card=card)

    def _build_message_card(self, build_data: Dict, app: App) -> Card:
        status = build_data['status']

        card = Card()
        card.add_header(
            title=f'{app.name} {self._get_icon(status=status)} {app.environment_name}',
            image_url=self._get_icon(status=status),
        )

        section = Section()
        if status in ['SUCCESS', 'FAILURE', 'INTERNAL_ERROR', 'TIMEOUT', 'CANCELLED', 'EXPIRED']:
            duration = self._parse_date(build_data['finishTime']) - self._parse_date(build_data['createTime'])
            section.add_text(
                title="Duration",
                content=duration,
            )

        if status == 'QUEUED':
            stats = self._get_stats(app=app, build_data=build_data)
            if 'diff' in stats:
                diff_message = '\n'.join(
                    ['\t'.join(item) for item in stats['diff']]
                )
                section.add_text(
                    title="Changes",
                    content=f"```{diff_message}```",
                )

        card.add_section(section=section)
        return card

    def _get_action(self, status: str) -> str:
        # https://cloud.google.com/cloud-build/docs/api/reference/rest/v1/projects.builds#status
        return {
            'STATUS_UNKNOWN': '???',
            'QUEUED': 'is about to be deployed to',
            'WORKING': 'is deploying to',
            'SUCCESS': 'has been deployed to',
            'FAILURE': 'failed to deploy to',
            'INTERNAL_ERROR': 'crashed when deploying to',
            'TIMEOUT': 'took too long to deploy to',
            'CANCELLED': 'has been cancelled to deploy to',
            'EXPIRED': 'took too long to start deployment to',
        }.get(status)

    def _get_icon(self, status: str) -> str:
        # https://cloud.google.com/cloud-build/docs/api/reference/rest/v1/projects.builds#status
        return {
            'STATUS_UNKNOWN': '',
            'QUEUED': '',
            'WORKING': '',
            'SUCCESS': '',
            'FAILURE': '',
            'INTERNAL_ERROR': '',
            'TIMEOUT': '',
            'CANCELLED': '',
            'EXPIRED': '',
        }.get(status)

    def _parse_date(self, date_str):
        return datetime.strptime(date_str, '%Y/%m/%dT%H:%M:%S.%fZ')

    def _get_stats(self, build_data: Dict, app: App) -> Dict:
        data = {}

        if self.detect_commit_diff:
            previous_build = self._get_previous_build(
                build_id=build_data['id'],
                trigger_id=build_data['buildTriggerId'],
            )
            commits = self._get_commits(
                repo=app.repository,
                current_revision=build_data['source']['revision'],
                previous_revision=previous_build.source.revision,
            )
            data['diff'] = commits

        return data

    def _get_previous_build(self, build_id, trigger_id):
        build = CloudBuild()
        current = False
        for one_build in build.get_builds(trigger_id=trigger_id, status='SUCCESS'):
            if one_build.id == build_id:
                current = True
            elif current:
                return one_build
        return None

    def _get_commits(
            self,
            repo: Repository,
            current_revision: str,
            previous_revision: str,
    ) -> List[Tuple[str, str, str]]:
        if repo.mirrored:  # GitHub
            g = Github(repo.access_token)
            git_repo = g.get_repo(repo.name)
            comparison = git_repo.compare(base=previous_revision, head=current_revision)
            return [
                (
                    commit.sha[:6],
                    commit.author.login,
                    commit.commit.message,
                )
                for commit in comparison.commits[:-1]  # exclude previous commit
            ]
        else:  # SourceRepo
            return []  # TODO: Get commits from SourceRepo


@dataclass
class Environment(Document):
    name: str
    network: Network = None
    project: Project = field(default_factory=Project.default)
    channel: NotificationChannel = None
    vars: List[EnvVar] = field(default_factory=list)

    def __post_init__(self):
        self.name = slugify(self.name)

    @property
    def pk(self) -> str:
        return self.name
