# More Information: https://cloud.google.com/iam/docs/
from typing import Dict, Any, List

from googleapiclient.errors import HttpError

from pilot.base import GoogleCloudPilotAPI


PolicyType = Dict[str, Any]
AccountType = Dict[str, Any]


class GoogleIAM(GoogleCloudPilotAPI):
    def __init__(self):
        super().__init__(
            serviceName='iam',
            version='v1',
        )

    async def get_service_account(self, name: str, project_id: str = None):
        project_id = project_id or self.project_id
        full_name = f'projects/{project_id}/serviceAccounts/{name}@{project_id}.iam.gserviceaccount.com'
        return self.client.projects().serviceAccounts().get(
            name=full_name,
        ).execute()

    async def create_service_account(self, name: str, display_name: str, project_id: str = None, exists_ok: bool = True) -> AccountType:
        try:
            service_account = self.client.projects().serviceAccounts().create(
                name='projects/' + project_id or self.project_id,
                body={
                    'accountId': name,
                    'serviceAccount': {
                        'displayName': display_name
                    }
                }).execute()
        except HttpError as e:
            if e.resp.status == 409 and exists_ok:
                service_account = await self.get_service_account(name=name, project_id=project_id)
            else:
                raise
        return service_account

    async def list_service_accounts(self, project_id: str = None) -> List[AccountType]:
        service_accounts = self.client.projects().serviceAccounts().list(
            name='projects/' + project_id or self.project_id
        ).execute()

        return service_accounts

    def _get_policy(self, email:str, project_id: str = None) -> PolicyType:
        project_id = project_id or self.project_id
        resource = f'projects/{project_id}/serviceAccounts/{email}'
        return self.client.projects().serviceAccounts().getIamPolicy(
            resource=resource,
        ).execute()

    def as_member(self, email: str) -> str:
        is_service_account = email.endswith('.gserviceaccount.com')
        prefix = 'serviceAccount' if is_service_account else 'member'
        return f'{prefix}:{email}'

    async def bind_member(self, target_email, member_email, role, project_id=None) -> PolicyType:
        policy = self._get_policy(email=target_email, project_id=project_id)
        role_id = role if role.startswith('organizations/') or role.startswith('roles/') else f'roles/{role}'
        member = self.as_member(email=member_email)

        try:
            binding = next(b for b in policy["bindings"] if b["role"] == role_id)
            if member in binding['members']:
                return policy
            binding['members'].append(member)
        except StopIteration:
            binding = {"role": role, "members": [member]}
            policy['bindings'].append(binding)

        resource = f'projects/{project_id}/serviceAccounts/{target_email}'
        policy = self.client.projects().serviceAccounts().setIamPolicy(
            resource=resource,
            body={"policy": policy, "updateMask": 'bindings'},
        ).execute()
        return policy

    async def remove_member(self, target_email: str, member_email: str, role: str, project_id: str = None) -> PolicyType:
        policy = self._get_policy(email=target_email, project_id=project_id)
        role_id = f'roles/{role}'
        member = self.as_member(email=member_email)

        try:
            binding = next(b for b in policy["bindings"] if b["role"] == role_id)
            binding["members"].remove(member)
        except StopIteration:
            return policy

        resource = f'projects/{project_id}/serviceAccounts/{target_email}'
        policy = self.client.projects().serviceAccounts().setIamPolicy(
            resource=resource,
            body={"policy": policy, "updateMask": 'bindings'},
        ).execute()
        return policy

    def get_compute_service_account(self, project_number=None) -> str:
        number = project_number or self._get_project_number(project_id=self.project_id)
        return f'{number}-compute@developer.gserviceaccount.com'

    def get_cloud_build_service_account(self, project_number=None) -> str:
        number = project_number or self._get_project_number(project_id=self.project_id)
        return f'{number}@cloudbuild.gserviceaccount.com'

    def get_cloud_run_service_account(self, project_number=None) -> str:
        number = project_number or self._get_project_number(project_id=self.project_id)
        return f'service-{number}@serverless-robot-prod.iam.gserviceaccount.com'
