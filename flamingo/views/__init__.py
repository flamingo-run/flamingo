from sanic import Blueprint

from views.app_views import apps
from views.build_pack_views import build_packs
from views.environment_views import environments


api = Blueprint.group(*[apps, build_packs, environments])

__all__ = (
    'api',
)
