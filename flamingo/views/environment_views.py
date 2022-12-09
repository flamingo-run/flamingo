from sanic import Blueprint
from sanic.request import Request
from sanic_rest import exceptions
from sanic_rest.views import DetailView, ListView, NestedListView, ResponseType

from models.environment import Environment
from services.clone import EnvironmentClone
from services.foundations import EnvironmentFoundation

environments = Blueprint("environments", url_prefix="/environments")


class EnvironmentListView(ListView):
    model = Environment


class EnvironmentDetailView(DetailView):
    model = Environment


class EnvironmentCloneView(NestedListView):
    nest_model = Environment

    async def perform_get(self, request: Request, nest_obj: Environment) -> ResponseType:
        raise exceptions.NotAllowedError()

    async def perform_post(self, request: Request, nest_obj: Environment) -> ResponseType:
        data, _ = self._parse_body(request=request)
        app = EnvironmentClone(environment=nest_obj).clone(
            env_name=data.get("environment_name"),
            project_id=data.get("project_id"),
            zone=data.get("zone"),
            vpc_connector=data.get("vpc_connector"),
        )

        return app.to_dict(), 201

    async def perform_put(self, request: Request, nest_obj: Environment) -> ResponseType:
        raise exceptions.NotAllowedError()

    async def perform_delete(self, request: Request, nest_obj: Environment) -> ResponseType:
        raise exceptions.NotAllowedError()


class EnvironmentInitializeView(NestedListView):
    nest_model = Environment

    async def perform_get(self, request: Request, nest_obj: Environment) -> ResponseType:
        foundation = EnvironmentFoundation(environment=nest_obj)
        jobs = foundation.get_jobs()
        return {"jobs": list(jobs.keys())}, 200

    async def perform_post(self, request: Request, nest_obj: Environment) -> ResponseType:
        foundation = EnvironmentFoundation(environment=nest_obj)
        jobs = foundation.build()
        return {"jobs": jobs}, 202

    async def perform_put(self, request: Request, nest_obj: Environment) -> ResponseType:
        raise exceptions.NotAllowedError()

    async def perform_delete(self, request: Request, nest_obj: Environment) -> ResponseType:
        raise exceptions.NotAllowedError()


environments.add_route(EnvironmentListView.as_view(), "/")
environments.add_route(EnvironmentDetailView.as_view(), "/<pk>")
environments.add_route(EnvironmentCloneView.as_view(), "/<nest_pk>/clone")
environments.add_route(EnvironmentInitializeView.as_view(), "/<pk>/init")
