import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from gcp_pilot.datastore import DoesNotExist, MultipleObjectsFound
from gcp_pilot.pubsub import Message
from requests import HTTPError
from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse, json
from sanic.views import HTTPMethodView
from sanic_rest import exceptions

from models.app import App
from models.deployment import Deployment, Event, Source

hooks = Blueprint('hooks', url_prefix='/hooks')


logger = logging.getLogger()


class CloudBuildHookView(HTTPMethodView):
    async def post(self, request: Request) -> HTTPResponse:
        message = Message.load(body=request.body.decode())
        payload = message.data

        logger.debug(f"BUILD HOOK PAYLOAD: {payload}")

        trigger_id = payload['buildTriggerId']

        git_source = payload['source'].get('gitSource', None)
        if not git_source:
            logger.warning(f"Ignoring build event from trigger {trigger_id}")
            return json({'status': 'done'}, 204)

        event = Event(
            status=payload['status'],
            created_at=self._get_timestamp(payload=payload),
            source=Source(
                url=git_source['url'],
                revision=git_source['revision'],
            )
        )

        try:
            app = self._get_app(trigger_id=trigger_id)
        except DoesNotExist:
            logger.warning(f"Ignoring build event from trigger {trigger_id}")
            return json({'status': 'done'}, 204)

        try:
            await self._register_event(
                app_id=app.id,
                build_id=payload['id'],
                event=event,
            )
        except HTTPError as e:
            return json({'error': f"Failed handling build hook: {e}", 'payload': payload}, 400)
        return json({'status': 'done'}, 202)

    def _get_timestamp(self, payload: Dict) -> Optional[datetime]:
        time_fields = ['finishTime', 'startTime', 'createTime']
        for time_field in time_fields:
            try:
                date_str = payload[time_field]
                return datetime.strptime(date_str.split('.')[0], '%Y-%m-%dT%H:%M:%S').astimezone(tz=timezone.utc)
            except KeyError:
                continue
        return None

    def _get_app(self, trigger_id: str) -> App:
        return App.documents.get(build__trigger_id=trigger_id)

    async def _register_event(self, app_id: str, build_id: str, event: Event):
        kwargs = dict(
            build_id=build_id,
            app_id=app_id
        )
        try:
            deployment = Deployment.documents.get(**kwargs)
        except DoesNotExist as e:
            if event.is_first:
                raise exceptions.ValidationError(
                    message=f"Event {event.status} received before deployment register"
                ) from e
            deployment = Deployment(**kwargs).save()
        except MultipleObjectsFound:
            logger.warning(f"Merging duplicated deployments with build_id={build_id}")
            deployment = Deployment.merge(**kwargs)
        await deployment.add_event(event=event, notify=True)


hooks.add_route(CloudBuildHookView.as_view(), '/build')
