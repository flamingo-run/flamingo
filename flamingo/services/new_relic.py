from dataclasses import dataclass
from datetime import datetime
from typing import Dict

import requests


NEW_RELIC_API_URL = 'https://api.newrelic.com/v2'


@dataclass
class NewRelicAPI:
    api_key: str

    def get_app(self, name: str):
        resource = 'applications'
        params = {'filter[name]': name}

        try:
            return self._list(resource=resource, params=params)[0]
        except IndexError:
            return None

    def notify_deployment(
            self,
            app_name: str,
            revision: str,
            user: str = '',
            changelog: str = '',
            description: str = '',
            timestamp: datetime = None,
    ):
        app_id = self.get_app(name=app_name)['id']
        resource = f'applications/{app_id}/deployments'
        deployment = dict(revision=revision)

        if changelog:
            deployment['changelog'] = changelog
        if description:
            deployment['description'] = description
        if timestamp:
            deployment['timestamp'] = timestamp.isoformat()
        if user:
            deployment['user'] = user

        payload = {
            "deployment": deployment
        }

        return self._post(
            resource=resource,
            payload=payload,
        )

    def _list(self, resource: str, params: Dict = None) -> Dict:
        response = requests.get(
            url=f'{NEW_RELIC_API_URL}/{resource}.json',
            params=params or {},
            headers={'X-Api-Key': self.api_key}
        )
        response.raise_for_status()
        return response.json()[resource]

    def _post(self, resource: str, payload: Dict = None) -> Dict:
        response = requests.post(
            url=f'{NEW_RELIC_API_URL}/{resource}.json',
            json=payload,
            headers={'X-Api-Key': self.api_key}
        )
        response.raise_for_status()
        return response.json()
