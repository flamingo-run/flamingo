# pylint: disable=too-many-lines
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Dict

import settings
from models import BuildPack
from models.base import Document, EmbeddedDocument, KeyValueEmbeddedDocument, random_password, Project
from models.environment import Environment
from pilot import GoogleIAM
from pilot import GoogleResourceManager
from pilot.build import GoogleCloudBuild, SubstitutionHelper
from pilot.source import GoogleCloudSourceRepo
from pilot.sql import GoogleCloudSQL
from pilot.storage import GoogleCloudStorage

REDACTED = '**********'


@dataclass
class EnvVar(KeyValueEmbeddedDocument):
    is_secret: bool = False

    def serialize(self) -> Dict:
        data = super().serialize()
        if self.is_secret:
            data['value'] = REDACTED
        return data


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
        return cls(
            name=app.name,
            display_name=app.name,
            description=f"{app.name} Service Account",
            roles=([settings.DEFAULT_ROLE] if settings.DEFAULT_ROLE else []) + ['run.invoker'],
            project=app.project,
        )

    @property
    def email(self) -> str:
        return f'{self.name}@{self.project.id}.iam.gserviceaccount.com'

    async def init(self):
        iam = GoogleIAM()
        grm = GoogleResourceManager()

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

    def serialize(self) -> dict:
        data = super().serialize()
        data['clone_url'] = self.clone_url
        return data

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
        data = await GoogleCloudSourceRepo().create_repo(
            name=self.name,
            project_id=self.project.id,
        )
        self.url = data['url']
        App.update(pk=app_pk, repository=self)


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
        sql = GoogleCloudSQL()

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
        gcs = GoogleCloudStorage()
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
    deploy_branch: str = 'master'
    post_build_commands: List[str] = field(default_factory=list)
    os_dependencies: List[str] = field(default_factory=list)
    labels: List[Label] = field(default_factory=list)
    project: Project = field(default_factory=Project.default_for_flamingo)
    memory: int = 256  # measured in Mi
    cpu: int = 1  # number of cores
    max_instances: int = 10

    _build_pack: BuildPack = None

    def serialize(self) -> dict:
        data = super().serialize()
        data['build_pack'] = self.build_pack.serialize()
        return data

    @property
    def build_pack(self):
        if not self._build_pack:
            self._build_pack = BuildPack.get(pk=self.build_pack_name)
        return self._build_pack

    @property
    def image_name(self) -> str:
        return f"gcr.io/{settings.FLAMINGO_PROJECT}/{self.name}:latest"

    def get_labels(self) -> List[Label]:
        all_labels = self.labels.copy()

        # https://cloud.google.com/run/docs/continuous-deployment-with-cloud-build#attach_existing_trigger_to_service
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

    _environment: Environment = None

    def __post_init__(self):
        environment = self.environment  # check if environment name actually exists, and caches it

        if not self.identifier:
            self.identifier = f'{self.name}-{environment.name}'

        self.build_setup.name = self.identifier

    def serialize(self) -> dict:
        data = super().serialize()
        data['environment'] = self.environment.serialize()
        return data

    @property
    def environment(self) -> Environment:
        if not self._environment:
            self._environment = Environment.get(pk=self.environment_name)
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
        self.assure_var(name='PROJECT_ID', default_value=self.project.id, is_secret=False)

    @property
    def pk(self) -> str:
        return self.identifier

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
            iam = GoogleIAM()
            grm = GoogleResourceManager()

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

        job = self.bucket.init()
        asyncio.create_task(job)

        job = self.database.init()
        asyncio.create_task(job)

        job = self.repository.init(app_pk=self.pk)
        asyncio.create_task(job)

        job = self.apply()
        asyncio.create_task(job)

    async def apply(self):
        build = GoogleCloudBuild()
        substitution = SubstitutionHelper()

        image_name = self.build_setup.image_name
        substitution.add(IMAGE_NAME=image_name)

        build_pack = self.build_setup.build_pack

        cache_loader = build.make_build_step(
            name='gcr.io/cloud-builders/docker',
            id="Image Cache",
            entrypoint='bash',
            args=["-c", f"docker pull {substitution.IMAGE_NAME} || exit 0"],
        )

        substitution.add(DOCKERFILE_LOCATION=build_pack.remote_dockerfile)
        build_pack_sync = build.make_build_step(
            name='gcr.io/google.com/cloudsdktool/cloud-sdk',
            id="Build Pack Download",
            args=['gsutil', 'cp', f'{substitution.DOCKERFILE_LOCATION}', 'Dockerfile'],
        )

        build_args = []
        for key, value in build_pack.get_build_args(app=self).items():
            substitution.add(**{key: value})
            build_args.extend(["--build-arg", getattr(substitution, key).as_kv])

        image_builder = build.make_build_step(
            name='gcr.io/cloud-builders/docker',
            id="Image Build",
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
            id="Image Upload",
            args=["push", f"{substitution.IMAGE_NAME}"],
        )

        for var in self.vars:
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
                id=title,
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

        substitution.add(
            REGION=self.region,
            CPU=self.build_setup.cpu,
            RAM=self.build_setup.memory,
            MAX_INSTANCES=self.build_setup.max_instances,
            SERVICE_ACCOUNT=self.service_account.email,
            PROJECT_ID=self.project.id,
            SERVICE_NAME=self.identifier,
        )
        deployer = build.make_build_step(
            id="Deploy",
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
                '--max-instances', f"{substitution.MAX_INSTANCES}",
                *label_params,
                '--quiet'
            ],
        )

        # TODO: Replace with https://cloud.google.com/cloud-build/docs/subscribe-build-notifications
        # url = self.environment.channel.webhook_url
        # payload = await self.environment.channel.make_deploy_payload(app_name=substitution.SERVICE_NAME)
        # snitch = build.make_build_step(
        #     id="Notify",
        #     name="pstauffer/curl",  # https://github.com/pstauffer/docker-curl
        #     args=[
        #         'curl',
        #         '--header', "'Content-Type: application/json'",
        #         '--request', "POST",
        #         '--data', f"'{json.dumps(payload)}'",
        #         url,
        #     ],
        # )

        steps = [
            cache_loader,
            build_pack_sync,
            image_builder,
            image_pusher,
            *custom,
            deployer,
            # snitch,
        ]

        response = await build.create_or_update_trigger(
            name=self.identifier,
            description="powered by Flamingo",
            repo_name=self.repository.name,
            branch_name=self.build_setup.deploy_branch,
            project_id=settings.FLAMINGO_PROJECT,
            steps=steps,
            images=[image_name],
            tags=self.build_setup.get_tags(),
            substitutions=substitution.as_dict,
        )

        trigger_not_bound = self.build_setup.trigger_id is None

        build_setup = self.build_setup
        build_setup.trigger_id = response.id
        App.update(pk=self.pk, build_setup=build_setup)

        # Since we need the Trigger ID inside the trigger yaml to be used as a CloudRun service label
        # The first time we create the trigger the yaml goes without the label, so we recreate it
        # adding the ID we just received
        if trigger_not_bound:
            return await self.apply()

        return response
