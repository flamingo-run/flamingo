from gcp_pilot.run import CloudRun

from models import App


class BoilerplateEngine:
    @classmethod
    def placeholder(cls, app: App):
        run = CloudRun()
        service_params = dict(
            service_name=app.identifier,
            location=app.region,
            project_id=app.project.id,
        )

        run.create_service(
            service_account=app.service_account.email,
            **service_params,
        )

        url = None
        while not url:
            service = run.get_service(**service_params)
            url = service['status'].get('url')
        return url
