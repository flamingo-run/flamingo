from dataclasses import field, dataclass

from gcp_pilot.build import AnyEventType, CloudBuild
from gcp_pilot.datastore import EmbeddedDocument
from github import Github

import exceptions
import settings
from models.project import Project


@dataclass
class Repository(EmbeddedDocument):
    name: str
    url: str = None
    project: Project = field(default_factory=Project.default_for_flamingo)
    access_token: str = None

    def __post_init__(self):
        if not self.access_token:
            self.access_token = settings.GIT_ACCESS_TOKEN
        if '/' not in self.name:
            raise exceptions.ValidationError("Repository name must have the format <user|org>/<repo-name>")
        self.url = f'https://github.com/{self.name}'

    def as_event(self, branch_name: str, tag_name: str) -> AnyEventType:
        build = CloudBuild()
        params = dict(
            branch_name=branch_name,
            tag_name=tag_name,
        )
        return build.make_github_event(
            url=self.url,
            **params,
        )

    def get_commit_diff(self, previous_revision: str, current_revision: str):
        g = Github(self.access_token)
        git_repo = g.get_repo(self.name)
        comparison = git_repo.compare(base=previous_revision, head=current_revision)
        return [
            (
                commit.sha[:6],
                commit.author.login,
                commit.commit.message,
            )
            for commit in comparison.commits[:-1]  # exclude previous commit
        ]
