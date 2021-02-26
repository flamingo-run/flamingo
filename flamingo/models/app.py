# pylint: disable=too-many-lines
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Union, TYPE_CHECKING
from urllib.parse import urlparse

from gcp_pilot.build import CloudBuild, AnyEventType
from gcp_pilot.datastore import Document, EmbeddedDocument
from gcp_pilot.exceptions import NotFound
from gcp_pilot.iam import IdentityAccessManager
from gcp_pilot.resource import ResourceManager
from gcp_pilot.run import CloudRun
from gcp_pilot.source import SourceRepository
from gcp_pilot.sql import CloudSQL
from gcp_pilot.storage import CloudStorage
from github import Github
from slugify import slugify

import exceptions
import settings
from models import BuildPack
from models.base import KeyValueEmbeddedDocument, random_password, Project, EnvVar, EnvVarSource
from models.environment import Environment

if TYPE_CHECKING:
    from utils.build_engine import CloudRunFactory, CloudFunctionsFactory  # pylint: disable=ungrouped-imports


logger = logging.getLogger()


@dataclass
class Label(KeyValueEmbeddedDocument):
    pass


@dataclass
class ServiceAccount(EmbeddedDocument):
    name: str
    description: str
    display_name: str
    roles: List[str] = field(default_factory=list)
    project: Project = field(default_factory=Project.default)

    @classmethod
    def default(cls, app: App) -> ServiceAccount:
        all_roles = ([settings.DEFAULT_ROLE] if settings.DEFAULT_ROLE else []) + [
            'run.invoker',  # allow authenticated integrations such as PubSub, Cloud Scheduler
        ]
        return cls(
            name=app.name,
            display_name=app.name,
            description=f"{app.name} Service Account",
            roles=all_roles,
            project=app.project,
        )

    @property
    def email(self) -> str:
        return f'{self.name}@{self.project.id}.iam.gserviceaccount.com'

    async def init(self):
        iam = IdentityAccessManager()
        grm = ResourceManager()

        await iam.create_service_account(
            name=self.name,
            display_name=f'App: {self.name}',
            project_id=self.project.id,
        )
        for role in self.roles:
            await grm.add_member(
                email=self.email,
                role=role,
                project_id=self.project.id,
            )


class RepoEngine(Enum):
    GITHUB = 'GITHUB'
    SOURCE_REPO = 'SOURCE_REPOSITORIES'


@dataclass
class Repository(EmbeddedDocument):
    name: str
    engine: str = RepoEngine.GITHUB.value
    url: str = None
    project: Project = field(default_factory=Project.default_for_flamingo)
    access_token: str = None

    def __post_init__(self):
        if self.engine == RepoEngine.GITHUB.value:
            if not self.access_token:
                self.access_token = settings.GIT_ACCESS_TOKEN
            if '/' not in self.name:
                raise exceptions.ValidationError("Repository name must have the user/org")
            self.url = f'https://github.com/{self.name}'

    @classmethod
    def default(cls, app: App) -> Repository:
        return cls(
            name=app.identifier,
        )

    async def init(self, app_pk: str):
        if self.engine == RepoEngine.SOURCE_REPO.value:
            data = await SourceRepository().create_repo(
                repo_name=self.name,
                project_id=self.project.id,
            )
            self.url = data['url']
            App.documents.update(pk=app_pk, repository=self)

    def as_event(self, branch_name: str, tag_name: str) -> AnyEventType:
        build = CloudBuild()
        params = dict(
            branch_name=branch_name,
            tag_name=tag_name,
        )
        if self.engine == RepoEngine.GITHUB.value:
            return build.make_github_event(
                url=self.url,
                **params,
            )
        return build.make_source_repo_event(
            repo_name=self.name,
            **params
        )

    def get_commit_diff(self, previous_revision: str, current_revision: str):
        if self.engine != RepoEngine.GITHUB.value:  # GitHub Only
            return []

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


@dataclass
class Database(EmbeddedDocument):
    instance: str
    name: str
    user: str
    password: str
    version: str = settings.DEFAULT_DB_VERSION
    tier: str = settings.DEFAULT_DB_TIER
    region: str = None
    project: Project = field(default_factory=Project.default)
    env_var: str = 'DATABASE_URL'
    high_availability: bool = False

    def __post_init__(self):
        if not self.user:
            self.user = f'app.{self.name}'
        if not self.region:
            self.region = self.project.region

    @classmethod
    def default(cls, app: App) -> Database:
        return cls(
            instance=app.identifier,
            name=app.path,
            user=f'app.{app.path}',
            password=random_password(20),
            project=app.project,
        )

    @property
    def engine(self) -> str:
        return self.version.split('_')[0].lower()

    @property
    def url(self) -> str:
        auth = f"{self.user}:{self.password}"
        url = f"//cloudsql/{self.connection_name}"
        return f"{self.engine}://{auth}@{url}/{self.name}"

    @property
    def connection_name(self) -> str:
        return f"{self.project.id}:{self.region}:{self.instance}"

    @property
    def as_env(self) -> List[EnvVar]:
        by_flamingo = EnvVarSource.FLAMINGO.value
        if '*' in self.env_var:
            prefix = self.env_var.replace('*', '')
            parts = urlparse(self.url)
            if parts.path.startswith('//'):  # CloudSQL socket
                instance, name = parts.path.rsplit('/', 1)
                instance = instance.replace('//', '/')
            else:
                instance, name = parts.hostname, parts.path.replace('/', '')
            db_envs = [
                EnvVar(key=f'{prefix}ENGINE', value=parts.scheme, is_secret=False, source=by_flamingo),
                EnvVar(key=f'{prefix}HOST', value=instance, is_secret=False, source=by_flamingo),
                EnvVar(key=f'{prefix}SCHEMA', value=name, is_secret=False, source=by_flamingo),
                EnvVar(key=f'{prefix}USERNAME', value=parts.username, is_secret=False, source=by_flamingo),
                EnvVar(key=f'{prefix}PASSWORD', value=parts.password, is_secret=True, source=by_flamingo),
            ]
        else:
            db_envs = [EnvVar(key=self.env_var, value=self.url, is_secret=True, source=by_flamingo)]
        return db_envs

    async def init(self):
        sql = CloudSQL()

        await sql.create_instance(
            name=self.instance,
            version=self.version,
            tier=self.tier,
            region=self.region,
            ha=self.high_availability,
            project_id=self.project.id,
            wait_ready=True,
        )
        await sql.create_database(
            name=self.name,
            instance=self.instance,
            project_id=self.project.id,
        )
        await sql.create_user(
            name=self.user,
            password=self.password,
            instance=self.instance,
            project_id=self.project.id,
        )


@dataclass
class Bucket(EmbeddedDocument):
    name: str
    env_var: str = 'GCS_BUCKET_NAME'
    region: str = None
    project: Project = field(default_factory=Project.default)

    def __post_init__(self):
        if not self.region:
            self.region = self.project.region

    @classmethod
    def default(cls, app: App) -> Bucket:
        return cls(
            name=app.identifier,
            project=app.project,
            region=app.region,
        )

    @property
    def url(self):
        return f'gs://{self.name}'

    @property
    def as_env(self) -> List[EnvVar]:
        return [EnvVar(key=self.env_var, value=self.name, is_secret=False, source=EnvVarSource.FLAMINGO.value)]

    async def init(self):
        gcs = CloudStorage()
        return await gcs.create_bucket(
            name=self.name,
            project_id=self.project.id,
            region=self.region,
        )


@dataclass
class BuildSetup(EmbeddedDocument):
    build_pack_name: str
    name: str = None
    trigger_id: str = None
    deploy_branch: str = None
    deploy_tag: str = None
    post_build_commands: List[str] = field(default_factory=list)
    os_dependencies: List[str] = field(default_factory=list)
    labels: List[Label] = field(default_factory=list)
    project: Project = field(default_factory=Project.default_for_flamingo)
    memory: int = 256  # measured in MB
    cpu: int = 1  # number of cores
    min_instances: int = 0
    max_instances: int = 10
    timeout: int = 60 * 15  # TODO: timeout above 15m is still beta on CloudRun
    concurrency: int = 80
    is_authenticated: bool = True
    entrypoint: str = None
    directory: str = None
    build_timeout: int = 60 * 30  # <https://cloud.google.com/cloud-build/docs/build-config#timeout_2>

    _build_pack: BuildPack = None

    def __post_init__(self):
        if not self.deploy_tag and not self.deploy_branch:
            raise exceptions.ValidationError(message="Either deploy_tag or deploy_branch must be provided")
        if self.max_instances < 1:
            self.max_instances = 1

    def serialize(self) -> dict:
        data = super().serialize()
        data['build_pack'] = self.build_pack.serialize()
        return data

    async def init(self):
        build = CloudBuild()

        url = f'{settings.FLAMINGO_URL}/hooks/build'
        await build.subscribe(
            subscription_id='flamingo',
            project_id=self.project.id,
            push_to_url=url,
            use_oidc_auth=True,
        )

    @property
    def build_pack(self):
        if not self._build_pack:
            self._build_pack = BuildPack.documents.get(id=self.build_pack_name)
        return self._build_pack

    @property
    def image_name(self) -> str:
        return f"gcr.io/{settings.FLAMINGO_PROJECT}/{self.name}:latest"

    def get_labels(self) -> List[Label]:
        all_labels = self.labels.copy()

        # https://cloud.google.com/run/docs/continuous-deployment-with-cloud-build#attach_existing_trigger_to_service
        # Does not seem to work when the trigger and the service deployed are not in the same project
        if self.trigger_id:
            all_labels.append(
                Label(key='gcb-trigger-id', value=self.trigger_id)
            )
        return all_labels

    def get_tags(self) -> List[str]:
        return self.build_pack.tags + [
            f'{self.name}',
        ]


@dataclass
class App(Document):
    name: str
    environment_name: str
    build_setup: BuildSetup
    repository: Repository = None
    identifier: str = None
    domains: List[str] = field(default_factory=list)
    vars: List[EnvVar] = field(default_factory=list)
    database: Database = None
    bucket: Bucket = None
    region: str = None
    service_account: ServiceAccount = None
    endpoint: str = None
    id: str = None

    _environment: Environment = None

    def __post_init__(self):
        environment = self.environment  # check if environment name actually exists, and caches it

        self.name = slugify(self.name)

        if not self.identifier:
            self.identifier = f'{self.name}-{environment.name}'

        if not self.region:
            self.region = self.project.region

        self.build_setup.name = self.identifier

        self.id = self.identifier

    def serialize(self) -> dict:
        data = super().serialize()
        data['environment'] = self.environment.serialize()
        return data

    @property
    def environment(self) -> Environment:
        if not self._environment:
            self._environment = Environment.documents.get(id=self.environment_name)
        return self._environment

    @property
    def project(self):
        return self.environment.project

    def set_env_var(self, var: EnvVar):
        self.unset_env_var(key=var.key)
        self.vars.append(var)

    def unset_env_var(self, key: str):
        self.vars = [
            existing_var for existing_var in self.vars if existing_var.key != key
        ]

    def add_default(self):
        if not self.database:
            self.database = Database.default(app=self)

        if not self.bucket:
            self.bucket = Bucket.default(app=self)

        if not self.service_account:
            default_account = ServiceAccount.default(app=self)
            self.service_account = default_account

        if not self.repository:
            default_repo = Repository.default(app=self)
            self.repository = default_repo

        if not self.domains and self.environment.network:
            self.domains = [
                f'{self.name}.{self.environment.name}.{self.environment.network.zone}',
            ]

        self.check_env_vars()

    def get_all_env_vars(self) -> List[EnvVar]:
        all_vars = self.vars.copy()

        if self.database:
            all_vars.extend(self.database.as_env)

        if self.bucket:
            all_vars.extend(self.bucket.as_env)

        by_flamingo = EnvVarSource.FLAMINGO.value
        all_vars.extend([
            EnvVar(key='APP_NAME', value=self.name, is_secret=False, source=by_flamingo),
            EnvVar(key='GCP_PROJECT', value=self.project.id, is_secret=False, source=by_flamingo),
            EnvVar(key='GCP_SERVICE_ACCOUNT', value=self.service_account.email, is_secret=False, source=by_flamingo),
            EnvVar(key='GCP_LOCATION', value=self.region, is_secret=False, source=by_flamingo),
        ])

        if self.domains:
            all_vars.extend([
                EnvVar(key='DOMAIN_URL', value=f'https://{self.domains[0]}', is_secret=False, source=by_flamingo),
            ])

        endpoint = self.get_url()
        all_vars.extend([
            EnvVar(key='GCP_APP_ENDPOINT', value=endpoint, is_secret=False, source=by_flamingo),
        ])

        all_vars.extend(self.environment.get_all_env_vars())
        all_vars.extend(self.build_setup.build_pack.get_all_env_vars())

        return all_vars

    def get_all_labels(self) -> List[Label]:
        all_labels = self.build_setup.get_labels()
        all_labels.extend([
            Label(key='service', value=self.identifier),
        ])
        return all_labels

    def get_url(self) -> str:
        if not self.endpoint:
            url = self.factory.get_url()
            App.documents.update(pk=self.pk, endpoint=url)
            self.endpoint = url
        return self.endpoint

    def check_env_vars(self):
        self.assure_var(env=EnvVar(key='SECRET', value=random_password(20), is_secret=True))

        all_vars = self.get_all_env_vars()
        implicit_vars = {var.key for var in all_vars if var.is_implicit}
        deduplicated_vars = {}
        for var in all_vars:
            if var.is_implicit:
                continue

            if var.key in implicit_vars or var.key in deduplicated_vars:
                # skip, because it's duplicated
                continue

            deduplicated_vars[var.key] = var

        self.vars = list(deduplicated_vars.values())

    @property
    def path(self) -> str:
        return self.name.replace('-', '_')

    def assure_var(self, env: EnvVar, overwrite: bool = False):
        for var in self.vars:
            if var.key == env.key:
                if overwrite:
                    var.value = env.value
                    var.is_secret = env.is_secret
                return
        self.vars.append(env)

    async def init(self):
        # TODO: replace with deployment manager, so we can rollback everything

        async def setup_iam():
            iam = IdentityAccessManager()
            grm = ResourceManager()

            await self.service_account.init()

            # By default, builds are done by GCP's account, not Flamingo Account.
            # Thus, this default account must have as many permissions as the app
            # because it MIGHT perform any custom commands during the build
            # that requires accessing the same resources (SQL, GCS) the app has access to
            # AND the CloudBuild account also must be able to deploy CloudRun services
            cloud_build_account = self.build_setup.project.cloud_build_account
            desired_roles = self.service_account.roles + ['run.admin']
            for role in desired_roles:
                await grm.add_member(
                    email=cloud_build_account,
                    role=role,
                    project_id=self.project.id,
                )

            # The CloudBuild account must also be able to act as the app's project's Compute account
            # TODO: add docs
            await iam.bind_member(
                target_email=self.project.compute_account,
                member_email=cloud_build_account,
                role='iam.serviceAccountUser',
                project_id=self.project.id,
            )

            # When deploying from other projects (https://cloud.google.com/run/docs/deploying#other-projects)...
            # the CloudRun agent must have permission to...
            cloud_run_account = self.project.cloud_run_account

            # ...pull container images from Flamingo's project
            await grm.add_member(
                email=cloud_run_account,
                role='containerregistry.ServiceAgent',
                project_id=settings.FLAMINGO_PROJECT,
            )
            # ... deploy as the app's service account
            await grm.add_member(
                email=self.project.cloud_run_account,
                role='iam.serviceAccountTokenCreator',
                project_id=self.project.id,
            )

        job = setup_iam()
        asyncio.create_task(job)

        if self.bucket:
            job = self.bucket.init()
            asyncio.create_task(job)

        if self.database:
            job = self.database.init()
            asyncio.create_task(job)

        job = self.repository.init(app_pk=self.pk)
        asyncio.create_task(job)

        job = self.build_setup.init()
        asyncio.create_task(job)

        job = self.apply()
        asyncio.create_task(job)

        async def setup_placeholder():
            url = self.factory.placeholder()
            App.documents.update(pk=self.pk, endpoint=url)

        if not self.endpoint:
            job = setup_placeholder()
            asyncio.create_task(job)

        # return job_names  # TODO: return scheduled jobs to use as response

    async def apply(self):
        trigger_id = await self.factory.build()

        trigger_not_bound = self.build_setup.trigger_id is None

        build_setup = self.build_setup
        build_setup.trigger_id = trigger_id
        App.documents.update(pk=self.pk, build_setup=build_setup)

        # Since we need the Trigger ID inside the trigger yaml to be used as a CloudRun service label
        # The first time we create the trigger the yaml goes without the label, so we recreate it
        # adding the ID we just received
        if trigger_not_bound:
            return await self.apply()

        return trigger_id

    @property
    def factory(self) -> Union[CloudRunFactory, CloudFunctionsFactory]:
        from utils.build_engine import get_factory  # pylint: disable=import-outside-toplevel
        return get_factory(app=self)
