from datetime import datetime, timezone
from typing import Dict

from gcp_pilot.datastore import DoesNotExist
from gcp_pilot.pubsub import Message
from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse, json
from sanic.views import HTTPMethodView

import models

hooks = Blueprint('hooks', url_prefix='/hooks')


class CloudBuildHookView(HTTPMethodView):
    async def post(self, request: Request) -> HTTPResponse:
        message = Message.load(body=request.body.decode())
        payload = message.data

        event = models.Event(
            status=payload['status'],
            created_at=self._get_timestamp(payload=payload),
            source=models.Source(
                url=payload['source']['gitSource']['url'],
                revision=payload['source']['gitSource']['revision'],
            )
        )
        app = self._get_app(trigger_id=payload['buildTriggerId'])
        await self._register_event(
            app_id=app.id,
            build_id=payload['id'],
            event=event,
        )
        return json({'status': 'done'}, 202)

    def _get_timestamp(self, payload: Dict) -> datetime:
        time_fields = ['finishTime', 'startTime', 'createTime']
        for time_field in time_fields:
            try:
                date_str = payload[time_field]
                return datetime.strptime(date_str.split('.')[0], '%Y-%m-%dT%H:%M:%S').astimezone(tz=timezone.utc)
            except KeyError:
                continue

    def _get_app(self, trigger_id: str) -> models.App:
        return models.App.documents.get(build_setup__trigger_id=trigger_id)

    async def _register_event(self, app_id: str, build_id: str, event: models.Event):
        kwargs = dict(
            build_id=build_id,
            app_id=app_id
        )
        try:
            deployment = models.Deployment.documents.get(**kwargs)
        except DoesNotExist:
            deployment = models.Deployment(**kwargs).save()

        await deployment.add_event(event=event, notify=True)


hooks.add_route(CloudBuildHookView.as_view(), '/build')
