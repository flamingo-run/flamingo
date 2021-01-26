# pylint: disable=too-many-lines
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Dict

from gcp_pilot.build import CloudBuild, SubstitutionHelper, AnyEventType
from gcp_pilot.datastore import Document, EmbeddedDocument
from gcp_pilot.iam import IAM
from gcp_pilot.resource import ResourceManager
from gcp_pilot.source import SourceRepository
from gcp_pilot.sql import CloudSQL
from gcp_pilot.storage import CloudStorage
from slugify import slugify

import exceptions
import settings
from models import BuildPack
from models.base import KeyValueEmbeddedDocument, random_password, Project, EnvVar
from models.environment import Environment


@dataclass
class Label(KeyValueEmbeddedDocument):
    pass


@dataclass
class ServiceAccount(EmbeddedDocument):
    name: str
    description: str
    display_name: str
    roles: List[str] = field(default=list)
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
        iam = IAM()
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


@dataclass
class Repository(EmbeddedDocument):
    name: str
    url: str = None
    mirrored: bool = False
    project: Project = field(default_factory=Project.default_for_flamingo)
    access_token: str = None

    def serialize(self) -> dict:
        data = super().serialize()
        data['clone_url'] = self.clone_url
        return data

    def __post_init__(self):
        if self.mirrored:
            if not self.access_token:
                self.access_token = settings.GIT_ACCESS_TOKEN
            if '/' not in self.name:
                raise exceptions.ValidationError("Repository name must have the user/org")

    @classmethod
    def default(cls, app: App) -> Repository:
        return cls(
            name=app.identifier,
        )

    @property
    def clone_url(self) -> str:
        if not self.mirrored:
            return f'ssh://source.developers.google.com:2022/p/{self.project.id}/r/{self.name}'
        return self.url

    async def init(self, app_pk: str):
        if not self.mirrored:
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
        if self.mirrored:
            return build.make_github_event(
                url=self.url,
                **params,
            )
        return build.make_source_repo_event(
            repo_name=self.name,
            **params
        )


@dataclass
class Database(EmbeddedDocument):
    instance: str
    name: str
    user: str
    password: str
    version: str = settings.DEFAULT_DB_VERSION
    tier: str = settings.DEFAULT_DB_TIER
    region: str = settings.DEFAULT_REGION
    project: Project = field(default_factory=Project.default)
    env_var: str = 'DATABASE_URL'
    high_availability: bool = False

    def __post_init__(self):
        if not self.user:
            self.user = f'app.{self.name}'

    @classmethod
    def default(cls, app: App) -> Database:
        return cls(
            instance=app.identifier,
            name=app.path,
            user=f'app.{app.path}',
            password=random_password(20),
            project=app.project,
            region=app.region,
        )

    @property
    def engine(self) -> str:
        return self.version.split('_')[0].lower()

    @property
    def url(self) -> str:
        auth = f"{self.user}:{self.password}"
        url = f"//cloudsql/{self.location}"
        return f"{self.engine}://{auth}@{url}/{self.name}"

    @property
    def location(self) -> str:
        return f"{self.project.id}:{self.region}:{self.instance}"

    @property
    def as_env(self) -> EnvVar:
        return EnvVar(key=self.env_var, value=self.url, is_secret=True)

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
    region: str = settings.DEFAULT_REGION
    project: Project = field(default_factory=Project.default)

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
    def as_env(self) -> EnvVar:
        return EnvVar(key=self.env_var, value=self.name, is_secret=False)

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
    memory: int = 256  # measured in Mi
    cpu: int = 1  # number of cores
    min_instances: int = 0
    max_instances: int = 10
    timeout: int = 60 * 15  # TODO: timeout above 15m is still beta
    concurrency: int = 80
    is_authenticated: bool = True

    _build_pack: BuildPack = None

    def __post_init__(self):
        if not self.deploy_tag and not self.deploy_branch:
            raise exceptions.ValidationError(message="Either deploy_tag or deploy_branch must be provided")

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
    region: str = settings.DEFAULT_REGION
    service_account: ServiceAccount = None
    id: str = None

    _environment: Environment = None

    def __post_init__(self):
        environment = self.environment  # check if environment name actually exists, and caches it

        self.name = slugify(self.name)

        if not self.identifier:
            self.identifier = f'{self.name}-{environment.name}'

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
            self.vars.append(self.database.as_env)

        if not self.bucket:
            self.bucket = Bucket.default(app=self)
            self.vars.append(self.bucket.as_env)

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

        self.assure_var(name='SECRET', default_value=random_password(20), is_secret=True)
        self.assure_var(name='APP_NAME', default_value=self.identifier, is_secret=False)
        self.assure_var(name='GCP_PROJECT', default_value=self.project.id, is_secret=False)
        self.assure_var(name='GCP_SERVICE_ACCOUNT', default_value=self.service_account.email, is_secret=False)
        self.assure_var(name='GCP_LOCATION', default_value=self.region, is_secret=False)

    @property
    def path(self) -> str:
        return self.name.replace('-', '_')

    def assure_var(self, name, default_value, is_secret=False):
        for var in self.vars:
            if var.key == name:
                return
        self.vars.append(EnvVar(key=name, value=default_value, is_secret=is_secret))

    async def init(self):
        # TODO: replace with deployment manager, so we can rollback everything

        async def setup_iam():
            iam = IAM()
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

    async def apply(self):
        build = CloudBuild()
        substitution = SubstitutionHelper()

        image_name = self.build_setup.image_name
        substitution.add(IMAGE_NAME=image_name)

        build_pack = self.build_setup.build_pack

        cache_loader = build.make_build_step(
            name='gcr.io/cloud-builders/docker',
            identifier="Image Cache",
            entrypoint='bash',
            args=["-c", f"docker pull {substitution.IMAGE_NAME} || exit 0"],
        )

        substitution.add(DOCKERFILE_LOCATION=build_pack.remote_dockerfile)
        build_pack_sync = build.make_build_step(
            name='gcr.io/google.com/cloudsdktool/cloud-sdk',
            identifier="Build Pack Download",
            args=['gsutil', 'cp', f'{substitution.DOCKERFILE_LOCATION}', 'Dockerfile'],
        )

        build_args = []
        for key, value in build_pack.get_build_args(app=self).items():
            substitution.add(**{key: value})
            build_args.extend(["--build-arg", getattr(substitution, key).as_kv])

        image_builder = build.make_build_step(
            name='gcr.io/cloud-builders/docker',
            identifier="Image Build",
            args=[
                "build",
                "-t",
                f"{substitution.IMAGE_NAME}",
                *build_args,
                "--cache-from", f"{substitution.IMAGE_NAME}",
                "."
            ],
        )

        # TODO: replace with image attribute?
        image_pusher = build.make_build_step(
            name="gcr.io/cloud-builders/docker",
            identifier="Image Upload",
            args=["push", f"{substitution.IMAGE_NAME}"],
        )

        all_vars = self.vars + self.environment.vars
        for var in all_vars:
            substitution.add(**{f'ENV_{var.key}': var.value})

        substitution.add(**{self.database.env_var: self.database.location})

        def _get_db_as_param(command: str) -> List[str]:
            return [command, str(getattr(substitution, self.database.env_var))]

        def _get_env_var_as_param(command: str) -> List[str]:
            params = []
            for env_var in self.vars:
                k = env_var.key
                v = str(getattr(substitution, f'ENV_{env_var.key}'))
                params.extend([command, f'{k}={v}'])
            return params

        def _make_command_step(title: str, command: str):
            # More info: https://github.com/GoogleCloudPlatform/ruby-docker/tree/master/app-engine-exec-wrapper
            # Caveats: default ComputeEngine service account here, not app's service account as it should be
            return build.make_build_step(
                identifier=title,
                name="gcr.io/google-appengine/exec-wrapper",
                args=[
                    "-i", f"{substitution.IMAGE_NAME}",
                    *_get_db_as_param('-s'),
                    *_get_env_var_as_param('-e'),
                    "--",
                    *command.split(),  # TODO Handle quoted command
                ],
            )

        custom = [
            _make_command_step(title=f"Custom {idx + 1} | {command}", command=command)
            for idx, command in enumerate(build_pack.get_extra_build_steps(app=self))
        ]

        db_params = _get_db_as_param('--add-cloudsql-instances')
        env_params = _get_env_var_as_param('--set-env-vars')

        label_params = ['--clear-labels']
        for label in self.build_setup.get_labels():
            label_params.extend(['--update-labels', f'{label.key}={label.value}'])

        auth_params = ['--allow-unauthenticated'] if not self.build_setup.is_authenticated else []

        substitution.add(
            REGION=self.region,
            CPU=self.build_setup.cpu,
            RAM=self.build_setup.memory,
            MIN_INSTANCES=self.build_setup.min_instances,
            MAX_INSTANCES=self.build_setup.max_instances,
            TIMEOUT=self.build_setup.timeout,
            CONCURRENCY=self.build_setup.concurrency,
            SERVICE_ACCOUNT=self.service_account.email,
            PROJECT_ID=self.project.id,
            SERVICE_NAME=self.identifier,
        )
        deployer = build.make_build_step(
            identifier="Deploy",
            name="gcr.io/google.com/cloudsdktool/cloud-sdk",
            entrypoint='gcloud',
            args=[
                "run", "services", "update", f"{substitution.SERVICE_NAME}",
                '--platform', 'managed',
                '--image', f"{substitution.IMAGE_NAME}",
                '--region', f"{substitution.REGION}",
                *db_params,
                *env_params,
                '--service-account', f"{substitution.SERVICE_ACCOUNT}",
                '--project', f"{substitution.PROJECT_ID}",
                '--memory', f"{substitution.RAM}Mi",
                '--cpu', f"{substitution.CPU}",
                # '--min-instances', f"{substitution.MIN_INSTANCES}",  # TODO: gcloud beta, not supported yet
                '--max-instances', f"{substitution.MAX_INSTANCES}",
                '--timeout', f"{substitution.TIMEOUT}",
                '--concurrency', f"{substitution.CONCURRENCY}",
                *auth_params,
                *label_params,
                '--quiet'
            ],
        )

        steps = [
            cache_loader,
            build_pack_sync,
            image_builder,
            image_pusher,
            *custom,
            deployer,
            # snitch,
        ]

        event = self.repository.as_event(
            branch_name=self.build_setup.deploy_branch,
            tag_name=self.build_setup.deploy_tag,
        )
        response = await build.create_or_update_trigger(
            name=self.identifier,
            description="powered by Flamingo 🦩",
            event=event,
            project_id=settings.FLAMINGO_PROJECT,
            steps=steps,
            images=[image_name],
            tags=self.build_setup.get_tags(),
            substitutions=substitution.as_dict,
        )

        trigger_not_bound = self.build_setup.trigger_id is None

        build_setup = self.build_setup
        build_setup.trigger_id = response.id
        App.documents.update(pk=self.pk, build_setup=build_setup)

        # Since we need the Trigger ID inside the trigger yaml to be used as a CloudRun service label
        # The first time we create the trigger the yaml goes without the label, so we recreate it
        # adding the ID we just received
        if trigger_not_bound:
            return await self.apply()

        return response

    async def notify_deploy(self, build_data: Dict):
        return await self.environment.channel.notify(
            build_data=build_data,
            app=self,
        )
