import logging
from dataclasses import dataclass, field
from typing import List

from gcp_pilot.build import CloudBuild, SubstitutionHelper

import settings
from models import App


logger = logging.getLogger()


@dataclass
class BuildTriggerFactory:
    app: App
    steps: List = field(default_factory=list)
    substitution: SubstitutionHelper = field(default_factory=SubstitutionHelper)

    def __post_init__(self):
        self._service = CloudBuild()

    @property
    def build_setup(self):
        return self.app.build_setup

    @property
    def vars(self):
        all_vars = self.app.vars + self.app.environment.vars
        if self.app.database:
            db_vars = self.app.database.as_env
            all_vars.extend(db_vars)
        return all_vars

    def _populate_substitutions(self):
        image_name = self.build_setup.image_name
        self.substitution.add(IMAGE_NAME=image_name)

        for var in self.vars:
            self.substitution.add(**{f'ENV_{var.key}': var.value})

        self.substitution.add(
            REGION=self.app.region,
            CPU=self.build_setup.cpu,
            RAM=self.build_setup.memory,
            MIN_INSTANCES=self.build_setup.min_instances,
            MAX_INSTANCES=self.build_setup.max_instances,
            TIMEOUT=self.build_setup.timeout,
            CONCURRENCY=self.build_setup.concurrency,
            SERVICE_ACCOUNT=self.app.service_account.email,
            PROJECT_ID=self.app.project.id,
            SERVICE_NAME=self.app.identifier,
        )

    def _get_db_as_param(self, command: str) -> List[str]:
        key = 'DATABASE_URL'
        self.substitution.add(**{key: self.app.database.url})
        if self.app.database:
            return [command, str(getattr(self.substitution, key))]
        return []

    def _get_env_var_as_param(self, command: str) -> List[str]:
        params = []
        for env_var in self.vars:
            k = env_var.key
            v = str(getattr(self.substitution, f'ENV_{env_var.key}'))
            params.extend([command, f'{k}={v}'])
        return params

    def _add_cache_step(self):
        cache_loader = self._service.make_build_step(
            name='gcr.io/cloud-builders/docker',
            identifier="Image Cache",
            entrypoint='bash',
            args=["-c", f"docker pull {self.substitution.IMAGE_NAME} || exit 0"],
        )
        self.steps.append(cache_loader)

    def _add_dockerfile_step(self):
        build_pack = self.build_setup.build_pack
        if build_pack.dockerfile_url:
            self.substitution.add(DOCKERFILE_LOCATION=build_pack.dockerfile_url)
            build_pack_sync = self._service.make_build_step(
                name='gcr.io/google.com/cloudsdktool/cloud-sdk',
                identifier="Build Pack Download",
                args=['gsutil', 'cp', f'{self.substitution.DOCKERFILE_LOCATION}', 'Dockerfile'],
            )
            self.steps.append(build_pack_sync)
        else:
            logger.info(f"No dockerfile predefined in BuildPack {build_pack.name}. I hope the repo has its own.")

    def _add_build_step(self):
        build_pack = self.build_setup.build_pack
        build_args = []
        for key, value in build_pack.get_build_args(app=self.app).items():
            self.substitution.add(**{key: value})
            build_args.extend(["--build-arg", getattr(self.substitution, key).as_kv])

        image_builder = self._service.make_build_step(
            name='gcr.io/cloud-builders/docker',
            identifier="Image Build",
            args=[
                "build",
                "-t",
                f"{self.substitution.IMAGE_NAME}",
                *build_args,
                "--cache-from", f"{self.substitution.IMAGE_NAME}",
                "."
            ],
        )
        self.steps.append(image_builder)

    def _add_push_step(self):
        # TODO: replace with image attribute?
        image_pusher = self._service.make_build_step(
            name="gcr.io/cloud-builders/docker",
            identifier="Image Upload",
            args=["push", f"{self.substitution.IMAGE_NAME}"],
        )
        self.steps.append(image_pusher)

    def _add_custom_command_steps(self):
        def _make_command_step(title: str, command: str):
            # More info: https://github.com/GoogleCloudPlatform/ruby-docker/tree/master/app-engine-exec-wrapper
            # Caveats: default ComputeEngine service account here, not app's service account as it should be
            # so it's the app's responsibility to impersonate
            return self._service.make_build_step(
                identifier=title,
                name="gcr.io/google-appengine/exec-wrapper",
                args=[
                    "-i", f"{self.substitution.IMAGE_NAME}",
                    *self._get_db_as_param('-s'),
                    *self._get_env_var_as_param('-e'),
                    "--",
                    *command.split(),  # TODO Handle quoted command
                ],
            )

        build_pack = self.build_setup.build_pack
        custom = [
            _make_command_step(title=f"Custom {idx + 1} | {command}", command=command)
            for idx, command in enumerate(build_pack.get_extra_build_steps(app=self))
        ]
        self.steps.extend(custom)

    def _add_deploy_step(self):
        db_params = self._get_db_as_param('--add-cloudsql-instances')

        env_params = self._get_env_var_as_param('--set-env-vars')

        label_params = ['--clear-labels']
        for label in self.build_setup.get_labels():
            label_params.extend(['--update-labels', f'{label.key}={label.value}'])

        auth_params = ['--allow-unauthenticated'] if not self.build_setup.is_authenticated else []

        deployer = self._service.make_build_step(
            identifier="Deploy",
            name="gcr.io/google.com/cloudsdktool/cloud-sdk",
            entrypoint='gcloud',
            args=[
                "run", "services", "update", f"{self.substitution.SERVICE_NAME}",
                '--platform', 'managed',
                '--image', f"{self.substitution.IMAGE_NAME}",
                '--region', f"{self.substitution.REGION}",
                *db_params,
                *env_params,
                '--service-account', f"{self.substitution.SERVICE_ACCOUNT}",
                '--project', f"{self.substitution.PROJECT_ID}",
                '--memory', f"{self.substitution.RAM}Mi",
                '--cpu', f"{self.substitution.CPU}",
                # '--min-instances', f"{substitution.MIN_INSTANCES}",  # TODO: gcloud beta, not supported yet
                '--max-instances', f"{self.substitution.MAX_INSTANCES}",
                '--timeout', f"{self.substitution.TIMEOUT}",
                '--concurrency', f"{self.substitution.CONCURRENCY}",
                *auth_params,
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
                "run", "services", "update-traffic", f"{self.substitution.SERVICE_NAME}",
                '--platform', 'managed',
                '--region', f"{self.substitution.REGION}",
                '--project', f"{self.substitution.PROJECT_ID}",
                '--to-latest',
            ],
        )
        self.steps.append(traffic)

    async def build(self) -> str:
        self._populate_substitutions()

        self._add_cache_step()
        self._add_dockerfile_step()
        self._add_build_step()
        self._add_push_step()
        self._add_custom_command_steps()
        self._add_deploy_step()
        self._add_traffic_step()

        event = self.app.repository.as_event(
            branch_name=self.build_setup.deploy_branch,
            tag_name=self.build_setup.deploy_tag,
        )
        if self.build_setup.deploy_branch:
            _event_str = f'pushed to {self.build_setup.deploy_branch}'
        else:
            _event_str = f'tagged {self.build_setup.deploy_tag}'
        description = f'🦩 Deploy to {self.build_setup.build_pack.target} when {_event_str}'

        response = await self._service.create_or_update_trigger(
            name=self.app.identifier,
            description=description,
            event=event,
            project_id=settings.FLAMINGO_PROJECT,
            steps=self.steps,
            images=[self.build_setup.image_name],
            tags=self.build_setup.get_tags(),
            substitutions=self.substitution.as_dict,
            timeout=self.build_setup.build_timeout,
        )

        return response.id
