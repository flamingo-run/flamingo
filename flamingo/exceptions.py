from dataclasses import dataclass


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
class NotFoundError(Exception):
    message: str = "Not found"
    status_code: int = 404


@dataclass
class NotAllowedError(Exception):
    message: str = "Not allowed"
    status_code: int = 405


@dataclass
class ForbiddenError(Exception):
    message: str = "Forbidden"
    status_code: int = 409
