import abc
import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from typing import Dict, Callable

from gcp_pilot.build import CloudBuild
from gcp_pilot.dns import CloudDNS, RecordType
from gcp_pilot.exceptions import NotFound
from gcp_pilot.iam import IdentityAccessManager
from gcp_pilot.resource import ResourceManager
from gcp_pilot.run import CloudRun
from gcp_pilot.sql import CloudSQL
from gcp_pilot.storage import CloudStorage

import settings
from models.app import App
from models.environment import Environment


class BaseFoundation(abc.ABC):
    def build(self):
        jobs = self.get_jobs()
        for job in jobs.values():
            asyncio.create_task(job())
        return list(jobs)

    @abstractmethod
    def get_jobs(self) -> Dict[str, Callable]:
        raise NotImplementedError()


@dataclass
class FlamingoFoundation(BaseFoundation):
    def get_jobs(self) -> Dict[str, Callable]:
        return {
            'bucket': self.setup_bucket,
        }

    async def setup_bucket(self):
        gcs = CloudStorage()
        await gcs.create_bucket(
            name=settings.FLAMINGO_GCS_BUCKET,
            region=settings.FLAMINGO_LOCATION,
            project_id=settings.FLAMINGO_PROJECT,
        )


@dataclass
class EnvironmentFoundation(BaseFoundation):
    environment: Environment

    def get_jobs(self) -> Dict[str, Callable]:
        # TODO Check flamingo permissions on project
        return {
            'notification': self.setup_build_notifications,
            'pubsub': self.setup_authenticated_pubsub,
        }

    async def setup_build_notifications(self):
        # FIXME: does not seem to work on other projects than flamingo
        build = CloudBuild()
        url = f'{settings.FLAMINGO_URL}/hooks/build'
        await build.subscribe(
            subscription_id='flamingo',
            project_id=self.environment.project.id,
            push_to_url=url,
            use_oidc_auth=True,
        )

    async def setup_authenticated_pubsub(self):
        grm = ResourceManager()
        await grm.add_member(
            email=self.environment.project.pubsub_account,
            role='iam.serviceAccountTokenCreator',
            project_id=self.environment.project.id,
        )


# TODO: replace with deployment manager, so we can rollback everything
@dataclass
class AppFoundation(BaseFoundation):
    app: App

    def get_jobs(self) -> Dict[str, Callable]:
        return {
            'iam': self.setup_iam,
            'bucket': self.setup_bucket,
            'placeholder': self.setup_placeholder,
            'database': self.setup_database,
            'custom_domains': self.setup_custom_domains,
        }

    async def setup_placeholder(self):
        url = self.app.factory.get_url()
        App.documents.update(pk=self.app.pk, endpoint=url)

    async def setup_bucket(self):
        bucket = self.app.bucket

        gcs = CloudStorage()
        return await gcs.create_bucket(
            name=bucket.name,
            project_id=bucket.project.id,
            region=bucket.region,
        )

    async def setup_database(self):
        sql = CloudSQL()

        database = self.app.database
        await sql.create_instance(
            name=database.instance,
            version=database.version,
            tier=database.tier,
            region=database.region,
            ha=database.high_availability,
            project_id=database.project.id,
            wait_ready=True,
        )
        await sql.create_database(
            name=database.name,
            instance=database.instance,
            project_id=database.project.id,
        )
        await sql.create_user(
            name=database.user,
            password=database.password,
            instance=database.instance,
            project_id=database.project.id,
        )

    async def setup_iam(self):
        iam = IdentityAccessManager()
        grm = ResourceManager()

        service_account = self.app.service_account

        await iam.create_service_account(
            name=service_account.name,
            display_name=service_account.display_name,
            project_id=service_account.project.id,
        )
        for role in service_account.roles:
            await grm.add_member(
                email=service_account.email,
                role=role,
                project_id=service_account.project.id,
            )

        # By default, builds are done by GCP's account, not Flamingo Account.
        # Thus, this default account must have as many permissions as the app
        # because it MIGHT perform any custom commands during the build
        # that requires accessing the same resources (SQL, GCS) the app has access to
        # AND the CloudBuild account also must be able to deploy CloudRun services
        cloud_build_account = self.app.build.project.cloud_build_account
        desired_roles = service_account.roles + ['run.admin']
        for role in desired_roles:
            await grm.add_member(
                email=cloud_build_account,
                role=role,
                project_id=self.app.project.id,
            )

        # The CloudBuild account must also be able to act as the app's project's Compute account
        # TODO: add docs
        await iam.bind_member(
            target_email=self.app.project.compute_account,
            member_email=cloud_build_account,
            role='iam.serviceAccountUser',
            project_id=self.app.project.id,
        )
        # ...and get buildpack's Dockerfile from Flamingo's project
        await grm.add_member(
            email=cloud_build_account,
            role='storage.objectViewer',
            project_id=settings.FLAMINGO_PROJECT,
        )
        # ...and store app's Dockerfile in build's project
        await grm.add_member(
            email=cloud_build_account,
            role='storage.admin',
            project_id=self.app.build.project.id,
        )

        # When deploying from other projects (https://cloud.google.com/run/docs/deploying#other-projects)...
        # the CloudRun agent must have permission to...
        cloud_run_account = self.app.project.cloud_run_account

        # ...pull container images from build's project
        await grm.add_member(
            email=cloud_run_account,
            role='containerregistry.ServiceAgent',
            project_id=self.app.build.project.id,
        )
        # ... deploy as the app's service account
        await grm.add_member(
            email=self.app.project.cloud_run_account,
            role='iam.serviceAccountTokenCreator',
            project_id=self.app.project.id,
        )

    async def setup_custom_domains(self):
        run = CloudRun()

        def _is_ready(domain_mapping):
            conditions = domain_mapping['status'].get('conditions', [])
            for condition in conditions:
                if condition['type'] != 'Ready':
                    continue
                status = condition['status']
                if status == 'True':
                    return True
                elif 'does not exist' in condition.get('message', ''):
                    raise NotFound(condition['message'])
                return True
            return False

        for domain in self.app.domains:
            mapped_domain = run.create_domain_mapping(
                domain=domain,
                service_name=self.app.name,
                project_id=self.app.project.id,
                location=self.app.region,
            )

            while not _is_ready(domain_mapping=mapped_domain):
                mapped_domain = run.get_domain_mapping(
                    domain=domain,
                    project_id=self.app.project.id,
                    location=self.app.region,
                )

            network = self.app.environment.network
            dns = CloudDNS(project_id=network.project.id)

            for record in mapped_domain['status']['resourceRecords']:
                dns.add_record(
                    zone_name=network.zone_name,
                    zone_dns=network.zone,
                    name=network.get_record_name(domain=record['name']),
                    record_type=RecordType.CNAME if record['type'] == 'CNAME' else RecordType.A,
                    record_data=[record['rrdata']],
                )
