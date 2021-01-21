import asyncio
from typing import List, Dict

from sanic import Blueprint
from sanic.request import Request

import exceptions
import models
from views.base import ActionView, DetailView, ListView, ResponseType

apps = Blueprint('apps', url_prefix='/apps')


class AppListView(ListView):
    model = models.App


class AppDetailView(DetailView):
    model = models.App


class AppBoostrapView(ActionView):
    model = models.App

    async def perform_get(self, request: Request, obj: models.App) -> ResponseType:
        raise exceptions.NotAllowedError()

    async def perform_post(self, request: Request, obj: models.App) -> ResponseType:
        obj.add_default()
        new_obj = obj.save()
        return new_obj.serialize(), 201

    async def perform_delete(self, request: Request, obj: models.App) -> ResponseType:
        raise exceptions.NotAllowedError()


class AppInitializeView(ActionView):
    model = models.App

    async def perform_get(self, request: Request, obj: models.App) -> ResponseType:
        raise exceptions.NotAllowedError()

    async def perform_post(self, request: Request, obj: models.App) -> ResponseType:
        job = obj.init()
        asyncio.create_task(job)

        return {}, 202

    async def perform_delete(self, request: Request, obj: models.App) -> ResponseType:
        raise exceptions.NotAllowedError()


class AppEnvVarsView(ActionView):
    model = models.App

    def _serialize_env_vars(self, app: models.App) -> List[Dict[str, str]]:
        return [
            env.serialize()
            for env in app.vars
        ]

    async def perform_get(self, request: Request, obj: models.App) -> ResponseType:
        payload = {
            'results': self._serialize_env_vars(app=obj)
        }
        return payload, 200

    async def perform_post(self, request: Request, obj: models.App) -> ResponseType:
        for key, value in request.json.items():
            env_var = models.EnvVar(key=key, value=value)
            obj.set_env_var(var=env_var)
        new_obj = obj.save()

        payload = {
            'results': self._serialize_env_vars(app=new_obj)
        }
        return payload, 201

    async def perform_delete(self, request: Request, obj: models.App) -> ResponseType:
        for key in request.json:
            obj.unset_env_var(key=key)
        new_obj = obj.save()

        payload = {
            'results': self._serialize_env_vars(app=new_obj)
        }
        return payload, 202


class AppApplyView(ActionView):
    model = models.App

    async def perform_get(self, request: Request, obj: models.App) -> ResponseType:
        raise exceptions.NotAllowedError()

    async def perform_post(self, request: Request, obj: models.App) -> ResponseType:
        await obj.apply()
        return {}, 201

    async def perform_delete(self, request: Request, obj: models.App) -> ResponseType:
        raise exceptions.NotAllowedError()


apps.add_route(AppListView.as_view(), '/')
apps.add_route(AppDetailView.as_view(), '/<pk>')
apps.add_route(AppBoostrapView.as_view(), '/<pk>/bootstrap')
apps.add_route(AppInitializeView.as_view(), '/<pk>/init')
apps.add_route(AppEnvVarsView.as_view(), '/<pk>/vars')
apps.add_route(AppApplyView.as_view(), '/<pk>/apply')
