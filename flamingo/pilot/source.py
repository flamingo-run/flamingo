# https://cloud.google.com/source-repositories/docs/reference/rest
from googleapiclient.errors import HttpError

from pilot.base import GoogleCloudPilotAPI


class GoogleCloudSourceRepo(GoogleCloudPilotAPI):
    _iam_roles = ['source.repos.create']

    def __init__(self):
        super().__init__(
            serviceName='sourcerepo',
            version='v1',
        )

    async def get_repo(self, name, project_id=None):
        parent = f'projects/{project_id or self.project_id}'
        name = f'{parent}/repos/{name}'
        return self.client.projects().repos().get(
            name=name,
        ).execute()

    async def create_repo(self, name, project_id=None, exists_ok=True):
        parent = f'projects/{project_id or self.project_id}'
        body = dict(
            name=f'{parent}/repos/{name}',
        )
        try:
            return self.client.projects().repos().create(
                parent=parent,
                body=body,
            ).execute()
        except HttpError as e:
            if e.resp.status == 409 and exists_ok:
                return await self.get_repo(name=name, project_id=project_id)
            raise
