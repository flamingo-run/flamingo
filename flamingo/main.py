# pylint: disable=wrong-import-position
import os
import sys

from sanic_rest import exceptions

sys.path.append(os.path.dirname(__file__))

from sanic import Sanic
from sanic_openapi import swagger_blueprint

import settings
import views

app = Sanic(name='flamingo', error_handler=exceptions.rest_error_handler)
app.update_config(settings)
app.blueprint(swagger_blueprint)

app.blueprint(views.api)

if __name__ == "__main__":
    app.run(host=os.environ.get('HOST', '0.0.0.0'), port=os.environ.get('PORT', 8000))
