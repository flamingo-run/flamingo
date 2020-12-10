import abc
import os

from google import auth
from googleapiclient.discovery import build

DEFAULT_PROJECT_ID = os.environ.get('PROJECT_ID')


class GoogleCloudPilotAPI(abc.ABC):
    _client_class = None
    _scopes = ['https://www.googleapis.com/auth/cloud-platform']
    _iam_roles = []

    def __init__(self, subject=None, **kwargs):
        self.credentials, project_id = self._build_credentials(subject=subject)
        self.project_id = kwargs.get('project') \
            or DEFAULT_PROJECT_ID \
            or getattr(self.credentials, 'project_id', project_id)

        self.client = (self._client_class or build)(
            credentials=self.credentials,
            **kwargs
        )

    @classmethod
    def _build_credentials(cls, subject=None):
        credentials, project_id = auth.default()
        if subject:
            credentials = credentials.with_subject(subject=subject)
        return credentials, project_id

    @property
    def oidc_token(self):
        return {'oidc_token': {'service_account_email': self.credentials.service_account_email}}

    async def add_permissions(self, email, project_id=None):
        for role in self._iam_roles:
            await GoogleResourceManager().add_member(
                email=email,
                role=role,
                project_id=project_id or self.project_id,
            )

    def _get_project_number(self, project_id):
        project = GoogleResourceManager().get_project(project_id=project_id)
        return project.projectNumber


class GoogleResourceManager(GoogleCloudPilotAPI):
    def __init__(self):
        super().__init__(
            serviceName='cloudresourcemanager',
            version='v1',
        )

    def as_member(self, email: str) -> str:
        is_service_account = email.endswith('.gserviceaccount.com')
        prefix = 'serviceAccount' if is_service_account else 'member'
        return f'{prefix}:{email}'

    def _get_policy(self, project_id: str = None, version: int = 1):
        policy = self.client.projects().getIamPolicy(
            resource=project_id or self.project_id,
            body={"options": {"requestedPolicyVersion": version}},
        ).execute()
        return policy

    async def add_member(self, email: str, role: str, project_id: str = None):
        policy = self._get_policy(project_id=project_id)
        role_id = role if role.startswith('organizations/') or role.startswith('roles/') else f'roles/{role}'
        member = self.as_member(email=email)

        try:
            binding = next(b for b in policy["bindings"] if b["role"] == role_id)
            if member in binding['members']:
                return policy
            binding['members'].append(member)
        except StopIteration:
            binding = {"role": role, "members": [member]}
            policy['bindings'].append(binding)

        policy = self.client.projects().setIamPolicy(
            resource=project_id or self.project_id,
            body={"policy": policy, "updateMask": 'bindings'},
        ).execute()
        return policy

    async def remove_member(self, email: str, role: str, project_id: str = None):
        policy = self._get_policy(project_id=project_id)
        role_id = f'roles/{role}'
        member = self.as_member(email=email)

        try:
            binding = next(b for b in policy["bindings"] if b["role"] == role_id)
            binding["members"].remove(member)
        except StopIteration:
            return policy

        policy = self.client.projects().setIamPolicy(
            resource=project_id or self.project_id,
            body={"policy": policy, "updateMask": 'bindings'},
        ).execute()
        return policy

    def get_project(self, project_id: str):
        return self.client.projects().get(
            projectId=project_id or self.project_id,
        ).execute()
