from typing import List, Dict

from sanic import Blueprint
from sanic.request import Request
from sanic_rest import exceptions

from models.app import App
from models.database import Database
from models.env_var import EnvVar
from services.bootstrap import AppBootstrap
from services.foundations import AppFoundation
from sanic_rest.views import ActionView, DetailView, ListView, ResponseType

apps = Blueprint('apps', url_prefix='/apps')


class AppListView(ListView):
    model = App


class AppDetailView(DetailView):
    model = App


class AppBoostrapView(ActionView):
    model = App

    async def perform_get(self, request: Request, obj: App) -> ResponseType:
        bootstrap = AppBootstrap(app=obj)
        changes = bootstrap.check()
        return changes, 200

    async def perform_post(self, request: Request, obj: App) -> ResponseType:
        bootstrap = AppBootstrap(app=obj)
        new_obj = bootstrap.apply()
        return new_obj.serialize(), 200

    async def perform_delete(self, request: Request, obj: App) -> ResponseType:
        raise exceptions.NotAllowedError()


class AppInitializeView(ActionView):
    model = App

    async def perform_get(self, request: Request, obj: App) -> ResponseType:
        foundation = AppFoundation(app=obj)
        jobs = foundation.get_jobs()
        return {'jobs': list(jobs.keys())}, 200

    async def perform_post(self, request: Request, obj: App) -> ResponseType:
        foundation = AppFoundation(app=obj)
        jobs = foundation.build()
        return {'jobs': jobs}, 202

    async def perform_delete(self, request: Request, obj: App) -> ResponseType:
        raise exceptions.NotAllowedError()


class AppEnvVarsView(ActionView):
    model = App

    async def _serialize_env_vars(self, app: App) -> List[Dict[str, str]]:
        env_vars = app.get_all_env_vars()
        return [
            env.serialize()
            for env in env_vars
        ]

    async def perform_get(self, request: Request, obj: App) -> ResponseType:
        payload = {
            'results': await self._serialize_env_vars(app=obj)
        }
        return payload, 200

    async def perform_post(self, request: Request, obj: App) -> ResponseType:
        for key, value in request.json.items():
            env_var = EnvVar(key=key, value=value)
            obj.set_env_var(var=env_var)
        new_obj = obj.save()

        payload = {
            'results': await self._serialize_env_vars(app=new_obj)
        }
        return payload, 201

    async def perform_delete(self, request: Request, obj: App) -> ResponseType:
        for key in request.json:
            obj.unset_env_var(key=key)
        new_obj = obj.save()

        payload = {
            'results': await self._serialize_env_vars(app=new_obj)
        }
        return payload, 202


class AppDatabaseView(ActionView):
    model = App

    async def perform_get(self, request: Request, obj: App) -> ResponseType:
        payload = obj.database.serialize()
        return payload, 200

    async def perform_post(self, request: Request, obj: App) -> ResponseType:
        data = request.json
        obj.database = Database(**data)
        new_obj = obj.save()

        payload = new_obj.database.serialize()
        return payload, 201

    async def perform_delete(self, request: Request, obj: App) -> ResponseType:
        obj.database = None
        obj.save()

        payload = {}
        return payload, 204


class AppApplyView(ActionView):
    model = App

    async def perform_get(self, request: Request, obj: App) -> ResponseType:
        try:
            obj.check_env_vars()
        except Exception as e:
            raise exceptions.ValidationError(message=str(e))

        return {'status': "Good to go"}, 200

    async def perform_post(self, request: Request, obj: App) -> ResponseType:
        trigger_id = await obj.apply()
        # TODO Add support to re-deploy
        return {'trigger_id': trigger_id}, 201

    async def perform_delete(self, request: Request, obj: App) -> ResponseType:
        raise exceptions.NotAllowedError()


apps.add_route(AppListView.as_view(), '/')
apps.add_route(AppDetailView.as_view(), '/<pk>')
apps.add_route(AppEnvVarsView.as_view(), '/<pk>/vars')
apps.add_route(AppDatabaseView.as_view(), '/<pk>/database')
apps.add_route(AppBoostrapView.as_view(), '/<pk>/bootstrap')
apps.add_route(AppInitializeView.as_view(), '/<pk>/init')
apps.add_route(AppApplyView.as_view(), '/<pk>/apply')
