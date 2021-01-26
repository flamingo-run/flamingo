from dataclasses import dataclass

from sanic.handlers import ErrorHandler
from sanic.response import json


@dataclass
class HttpException(Exception):
    message: str
    status_code: int

    @property
    def response(self):
        return {'error': self.message}


@dataclass
class ValidationError(HttpException):
    status_code: int = 400


@dataclass
class NotFoundError(HttpException):
    message: str = "Not found"
    status_code: int = 404


@dataclass
class NotAllowedError(HttpException):
    message: str = "Not allowed"
    status_code: int = 405


@dataclass
class ForbiddenError(HttpException):
    message: str = "Forbidden"
    status_code: int = 409


def _http_error_handler(request, exc):
    return json(exc.response, exc.status_code)


rest_error_handler = ErrorHandler()
rest_error_handler.add(exception=HttpException, handler=_http_error_handler)
