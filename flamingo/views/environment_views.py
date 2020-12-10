from sanic import Blueprint

import models
from views.base import DetailView, ListView

environments = Blueprint('environments', url_prefix='/environments')


class EnvironmentListView(ListView):
    model = models.Environment


class EnvironmentDetailView(DetailView):
    model = models.Environment


environments.add_route(EnvironmentListView.as_view(), '/')
environments.add_route(EnvironmentDetailView.as_view(), '/<pk>')
