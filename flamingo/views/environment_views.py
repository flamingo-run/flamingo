from sanic import Blueprint
from sanic.request import Request

import exceptions
from models.environment import Environment
from services.foundations import EnvironmentFoundation
from views.base import DetailView, ListView, ActionView, ResponseType

environments = Blueprint('environments', url_prefix='/environments')


class EnvironmentListView(ListView):
    model = Environment


class EnvironmentDetailView(DetailView):
    model = Environment


class EnvironmentInitializeView(ActionView):
    model = Environment

    async def perform_get(self, request: Request, obj: Environment) -> ResponseType:
        foundation = EnvironmentFoundation(environment=obj)
        jobs = foundation.get_jobs()
        return {'jobs': list(jobs.keys())}, 200

    async def perform_post(self, request: Request, obj: Environment) -> ResponseType:
        foundation = EnvironmentFoundation(environment=obj)
        jobs = foundation.build()
        return {'jobs': jobs}, 202

    async def perform_delete(self, request: Request, obj: Environment) -> ResponseType:
        raise exceptions.NotAllowedError()


environments.add_route(EnvironmentListView.as_view(), '/')
environments.add_route(EnvironmentDetailView.as_view(), '/<pk>')
environments.add_route(EnvironmentInitializeView.as_view(), '/<pk>/init')
