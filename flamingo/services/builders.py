import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, ClassVar, Tuple, Union

from gcp_pilot.build import CloudBuild, Substitutions
from gcp_pilot.exceptions import NotFound
from gcp_pilot.run import CloudRun
from google.cloud.devtools import cloudbuild_v1

import settings
from models.app import App
from models.base import KeyValue
from models.buildpack import Target
from models.schedule import ScheduledInvocation
from services.alias_engine import AliasEngine

logger = logging.getLogger()


@dataclass
class BuildTriggerFactory(ABC):
    DB_CONN_KEY: ClassVar = 'DATABASE_CONNECTION'
    DOCKERFILE_KEY: ClassVar = 'DOCKERFILE_LOCATION'
    ENV_PREFIX_KEY: ClassVar = 'ENV_'

    app: App
    steps: List[cloudbuild_v1.BuildStep] = field(default_factory=list)

    _substitution: Substitutions = None
    _setup_params: KeyValue = None
    _env_vars: KeyValue = None
    _build_args: KeyValue = None

    def __post_init__(self):
        self._service = CloudBuild()

        # Cache locally some references
        self._build = self.app.build
        self._build_pack = self.app.build.build_pack

    def init(self):
        # key-value pairs
        self._setup_params = self._get_setup_params()
        self._env_vars, self._build_args = self._get_env_and_build_args()
        self._substitution = self._populate_substitutions()

    def _populate_substitutions(self) -> Substitutions:
        substitution = Substitutions()

        substitution.add(**self._setup_params)
        substitution.add(**self._build_args)
        substitution.add(**{f'{self.ENV_PREFIX_KEY}{key}': value for key, value in self._env_vars.items()})

        return substitution

    @abstractmethod
    def _get_setup_params(self) -> KeyValue:
        raise NotImplementedError()

    def _get_env_and_build_args(self) -> Tuple[KeyValue, KeyValue]:
        all_env_vars = {var.key: var.value for var in self.app.get_all_env_vars()}
        all_build_args = self._build.build_pack.get_build_args(app=self.app)

        replacements = dict()
        replacements.update(self._setup_params)
        replacements.update(all_env_vars)
        replacements.update(all_build_args)

        env_var_engine = AliasEngine(
            items=all_env_vars,
            replacements=replacements,
        )

        build_args_engine = AliasEngine(
            items=all_build_args,
            replacements=replacements,
        )

        return dict(env_var_engine.items()), dict(build_args_engine.items())

    def _get_db_as_param(self, command: str) -> List[str]:
        if self.app.database:
            return [command, str(getattr(self._substitution, self.DB_CONN_KEY))]
        return []

    def _get_env_var_as_param(self, command: str = '--set-env-var') -> List[str]:
        params = []
        for key, value in self._env_vars.items():
            sub_variable = getattr(self._substitution, f'{self.ENV_PREFIX_KEY}{key}')
            params.extend([command, sub_variable.as_env_var(key=key)])
        return params

    def _get_build_args_as_param(self, command: str = '--build-arg') -> List[str]:
        build_params = []
        for key, value in self._build_args.items():
            sub_variable = getattr(self._substitution, key)
            build_params.extend([command, sub_variable.as_env_var()])
        return build_params

    @abstractmethod
    def _add_steps(self) -> None:
        raise NotImplementedError()

    def _get_description(self) -> str:
        if self._build.deploy_branch:
            _event_str = f'pushed to {self._build.deploy_branch}'
        else:
            _event_str = f'tagged {self._build.deploy_tag}'
        return f'🦩 Deploy to {self._build.build_pack.target} when {_event_str}'

    def _add_scheduled_invocation_step(self, scheduled_invocation: ScheduledInvocation, wait_for: str):
        schedule_name = f"{self.app.identifier}--{scheduled_invocation.name}"

        auth_params = []
        if self._build.is_authenticated:
            auth_params = [
                '--oidc-token-audience', f"{self.app.endpoint}",
                '--oidc-service-account-email', f"{self._substitution.SERVICE_ACCOUNT}",
            ]

        scheduler = self._service.make_build_step(
            identifier=f"Schedule {scheduled_invocation.name}",
            name="gcr.io/google.com/cloudsdktool/cloud-sdk",
            entrypoint='gcloud',
            args=[
                "beta", "scheduler", "jobs", "create", "http", "deploy", f"{schedule_name}",
                '--uri', f"{self.app.endpoint}{scheduled_invocation.path}",
                '--schedule', f'{scheduled_invocation.cron}',
                '--http-method', f'{scheduled_invocation.method}',
                '--headers', f'Content-Type={scheduled_invocation.content_type}',
                '--region', f"{self._substitution.REGION}",
                *auth_params,
            ],
            # wait_for=[wait_for],
        )
        self.steps.append(scheduler)

    async def build(self) -> str:
        self.init()
        self._add_steps()

        last_step_id = self.steps[-1].id
        for scheduled_invocation in self.app.scheduled_invocations:
            self._add_scheduled_invocation_step(
                scheduled_invocation=scheduled_invocation,
                wait_for=last_step_id,
            )

        event = self.app.repository.as_event(
            branch_name=self._build.deploy_branch,
            tag_name=self._build.deploy_tag,
        )
        description = self._get_description()

        response = await self._service.create_or_update_trigger(
            name=self.app.identifier,
            description=description,
            event=event,
            project_id=settings.FLAMINGO_PROJECT,
            steps=self.steps,
            images=[self._build.get_image_name(app=self.app)],
            tags=self._build.get_tags(app=self.app),
            substitutions=self._substitution,
            timeout=self._build.build_timeout,
        )

        return response.id

    @abstractmethod
    def get_url(self):
        raise NotImplementedError()


@dataclass
class CloudRunFactory(BuildTriggerFactory):
    def _add_steps(self) -> None:
        self._add_cache_step()
        self._add_dockerfile_step()
        self._add_build_step()
        self._add_push_step()
        self._add_custom_command_steps()
        self._add_deploy_step()
        self._add_traffic_step()

    def _get_setup_params(self) -> KeyValue:
        params = dict(
            IMAGE_NAME=self._build.get_image_name(app=self.app),
            REGION=self.app.region,
            CPU=self._build.cpu,
            RAM=self._build.memory,
            MIN_INSTANCES=self._build.min_instances,
            MAX_INSTANCES=self._build.max_instances,
            TIMEOUT=self._build.timeout,
            CONCURRENCY=self._build.concurrency,
            SERVICE_ACCOUNT=self.app.service_account.email,
            PROJECT_ID=self.app.project.id,
            SERVICE_NAME=self.app.identifier,
        )
        if self._build_pack.dockerfile_url:
            params[self.DOCKERFILE_KEY] = self._build_pack.dockerfile_url

        if self.app.database:
            params[self.DB_CONN_KEY] = self.app.database.connection_name
        return params

    def _add_cache_step(self):
        cache_loader = self._service.make_build_step(
            name='gcr.io/cloud-builders/docker',
            identifier="Image Cache",
            entrypoint='bash',
            args=["-c", f"docker pull {self._substitution.IMAGE_NAME} || exit 0"],
        )
        self.steps.append(cache_loader)

    def _add_dockerfile_step(self):
        if self._build_pack.dockerfile_url:
            sub_variable = getattr(self._substitution, self.DOCKERFILE_KEY)

            build_pack_sync = self._service.make_build_step(
                name='gcr.io/google.com/cloudsdktool/cloud-sdk',
                identifier="Build Pack Download",
                args=['gsutil', 'cp', str(sub_variable), 'Dockerfile'],
            )
            self.steps.append(build_pack_sync)
        else:
            logger.info(f"No dockerfile predefined in BuildPack {self._build_pack.name}. I hope the repo has its own.")

    def _add_build_step(self):
        build_args = self._get_build_args_as_param()

        image_builder = self._service.make_build_step(
            name='gcr.io/cloud-builders/docker',
            identifier="Image Build",
            args=[
                "build",
                "-t",
                f"{self._substitution.IMAGE_NAME}",
                *build_args,
                "--cache-from", f"{self._substitution.IMAGE_NAME}",
                "."
            ],
        )
        self.steps.append(image_builder)

    def _add_push_step(self):
        # TODO: replace with image attribute?
        image_pusher = self._service.make_build_step(
            name="gcr.io/cloud-builders/docker",
            identifier="Image Upload",
            args=["push", f"{self._substitution.IMAGE_NAME}"],
        )
        self.steps.append(image_pusher)

    def _add_custom_command_steps(self):
        db_params = self._get_db_as_param('-s')
        env_params = self._get_env_var_as_param('-e')

        def _make_command_step(title: str, command: str):
            # More info: https://github.com/GoogleCloudPlatform/ruby-docker/tree/master/app-engine-exec-wrapper
            # Caveats: default ComputeEngine service account here, not app's service account as it should be
            # so it's the app's responsibility to impersonate
            return self._service.make_build_step(
                identifier=title,
                name="gcr.io/google-appengine/exec-wrapper",
                args=[
                    "-i", f"{self._substitution.IMAGE_NAME}",
                    *db_params,
                    *env_params,
                    "--",
                    *command.split(),  # TODO Handle quoted command
                ],
            )

        custom = [
            _make_command_step(title=f"Custom {idx + 1} | {command}", command=command)
            for idx, command in enumerate(self._build_pack.get_extra_build_steps(app=self.app))
        ]
        self.steps.extend(custom)

    def _add_deploy_step(self):
        db_params = self._get_db_as_param('--add-cloudsql-instances')
        env_params = self._get_env_var_as_param('--set-env-vars')

        label_params = ['--clear-labels']
        for label in self.app.get_all_labels():
            label_params.extend(['--update-labels', label.as_kv])

        deployer = self._service.make_build_step(
            identifier="Deploy",
            name="gcr.io/google.com/cloudsdktool/cloud-sdk",
            entrypoint='gcloud',
            args=[
                "run", "services", "update", f"{self._substitution.SERVICE_NAME}",
                '--platform', 'managed',
                '--image', f"{self._substitution.IMAGE_NAME}",
                '--region', f"{self._substitution.REGION}",
                *db_params,
                *env_params,
                '--service-account', f"{self._substitution.SERVICE_ACCOUNT}",
                '--project', f"{self._substitution.PROJECT_ID}",
                '--memory', f"{self._substitution.RAM}Mi",
                '--cpu', f"{self._substitution.CPU}",
                # '--min-instances', f"{substitution.MIN_INSTANCES}",  # TODO: gcloud beta, not supported yet
                '--max-instances', f"{self._substitution.MAX_INSTANCES}",
                '--timeout', f"{self._substitution.TIMEOUT}",
                '--concurrency', f"{self._substitution.CONCURRENCY}",
                *label_params,
                '--quiet'
            ],
        )
        self.steps.append(deployer)

    def _add_traffic_step(self):
        # If roll-backed, just a deploy is not enough to redirect traffic to a new revision
        traffic = self._service.make_build_step(
            identifier="Redirect Traffic",
            name="gcr.io/google.com/cloudsdktool/cloud-sdk",
            entrypoint='gcloud',
            args=[
                "run", "services", "update-traffic", f"{self._substitution.SERVICE_NAME}",
                '--platform', 'managed',
                '--region', f"{self._substitution.REGION}",
                '--project', f"{self._substitution.PROJECT_ID}",
                '--to-latest',
            ],
        )
        self.steps.append(traffic)

    def get_url(self):
        run = CloudRun()
        try:
            service = run.get_service(
                service_name=self.app.identifier,
                project_id=self.app.project.id,
                location=self.app.region,
            )
            url = service['status']['url']
        except NotFound as e:
            logger.warning(str(e))
            url = self._create_placeholder()
        return url

    def _create_placeholder(self):
        run = CloudRun()
        service_params = dict(
            service_name=self.app.identifier,
            location=self.app.region,
            project_id=self.app.project.id,
        )

        run.create_service(
            service_account=self.app.service_account.email,
            **service_params,
        )

        url = None
        while not url:
            service = run.get_service(**service_params)
            url = service['status'].get('url')
        return url


@dataclass
class CloudFunctionsFactory(BuildTriggerFactory):
    # TODO: setup this <https://cloud.google.com/functions/docs/reference/iam/roles#additional-configuration>
    def _get_setup_params(self) -> KeyValue:
        from gcp_pilot.functions import CloudFunctions

        if self._build.deploy_tag:
            kwargs = dict(tag=self._build.deploy_tag)
        elif self._build.deploy_branch:
            kwargs = dict(branch=self._build.deploy_branch)
        else:
            kwargs = dict()

        directory = self._build.directory
        repo_url = CloudFunctions.build_repo_source(
            name=self.app.repository.name,
            directory=directory,
            project_id=self.app.repository.project.id,
            **kwargs,
        )['url']

        params = dict(
            REGION=self.app.region,
            CPU=self._build.cpu,
            RAM=self._build.memory,
            MAX_INSTANCES=self._build.max_instances,
            TIMEOUT=self._build.timeout,
            SERVICE_ACCOUNT=self.app.service_account.email,
            PROJECT_ID=self.app.project.id,
            SERVICE_NAME=self.app.identifier,
            SOURCE=repo_url,
            ENTRYPOINT=self._build.entrypoint,
        )
        if self.app.database:
            params[self.DB_CONN_KEY] = self.app.database.connection_name
        return params

    def _add_deploy_step(self):
        env_params = self._get_env_var_as_param('--set-env-vars')

        label_params = ['--clear-labels']
        for label in self.app.get_all_labels():
            label_params.extend(['--update-labels', label.as_kv])

        auth_params = ['--allow-unauthenticated'] if self._build.is_authenticated else []

        deployer = self._service.make_build_step(
            identifier="Deploy",
            name="gcr.io/google.com/cloudsdktool/cloud-sdk",
            entrypoint='gcloud',
            args=[
                "functions", "deploy", f"{self._substitution.SERVICE_NAME}",
                '--runtime', f"{self._substitution.RUNTIME_VERSION}",
                '--source', f"{self._substitution.SOURCE}",
                '--entry-point', f"{self._substitution.ENTRYPOINT}",
                '--region', f"{self._substitution.REGION}",
                *env_params,
                '--service-account', f"{self._substitution.SERVICE_ACCOUNT}",
                '--project', f"{self._substitution.PROJECT_ID}",
                '--memory', f"{self._substitution.RAM}MB",
                '--max-instances', f"{self._substitution.MAX_INSTANCES}",
                '--timeout', f"{self._substitution.TIMEOUT}",
                *label_params,
                *auth_params,
                '--trigger-http',
                '--quiet'
            ],
        )
        self.steps.append(deployer)

    def _add_steps(self) -> None:
        self._add_deploy_step()

    def get_url(self):
        # TODO: Create a placeholder
        return f'https://{self.app.region}-{self.app.project.id}.cloudfunctions.net/{self.app.identifier}'


def get_factory(app: App) -> Union[CloudRunFactory, CloudFunctionsFactory]:
    factories = {
        Target.CLOUD_RUN.value: CloudRunFactory,
        Target.CLOUD_FUNCTIONS.value: CloudFunctionsFactory,
    }
    return factories[app.build.build_pack.target](app=app)
