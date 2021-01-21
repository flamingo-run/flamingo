from typing import Dict

from gcp_pilot.pubsub import Message
from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse, json
from sanic.views import HTTPMethodView


import models

hooks = Blueprint('hooks', url_prefix='/hooks')


class CloudBuildHookView(HTTPMethodView):
    async def post(self, request: Request) -> HTTPResponse:
        message = Message.load(body=request.body)
        payload = message.data
        app = self._get_app(payload=payload)
        await app.notify_deploy(build_data=payload)
        return json({'status': 'done'}, 202)

    def _get_app(self, payload: Dict) -> models.App:
        trigger_id = payload['buildTriggerId']
        return models.App.get(build_setup__trigger_id=trigger_id)


hooks.add_route(CloudBuildHookView.as_view(), '/build')
