from __future__ import annotations

import random
import string
from abc import ABC
from dataclasses import dataclass, fields
from typing import Type, Generator, get_type_hints, get_args, Dict

from google.cloud.firestore_v1 import CollectionReference

import settings
from pilot import GoogleIAM, GoogleResourceManager


@dataclass
class DoesNotExist(Exception):
    cls: Type[EmbeddedDocument]
    pk: str


def random_password(length: int) -> str:
    password_characters = string.ascii_letters + string.digits
    return ''.join(random.choice(password_characters) for _ in range(length))


operators = {
    'eq': '==',
    'gt': '>',
    'gte': '>=',
    'lt': '<',
    'lte': '<=',
    'in': 'in',
}


def query_operator(key: str) -> tuple:
    parts = key.split('__')
    field = parts[0]
    if len(parts) == 1:
        operator = '=='
    else:
        try:
            operator = operators[parts[1]]
        except KeyError as e:
            raise Exception(f"Unsupported query operator {parts[1]}") from e
    return field, operator


@dataclass
class EmbeddedDocument:
    @classmethod
    def _fields(cls):
        resolved_hints = get_type_hints(cls)
        field_names = [field.name for field in fields(cls)]
        return {
            name: resolved_hints[name]
            for name in field_names
            if not name.startswith('_')
        }

    @classmethod
    def deserialize(cls, **kwargs) -> EmbeddedDocument:
        return cls._from_dict(**kwargs)

    @classmethod
    def _from_dict(cls, **kwargs) -> EmbeddedDocument:
        data = kwargs.copy()

        def _build(klass, value):
            if value is None:
                return value

            if issubclass(klass, EmbeddedDocument):
                return klass._from_dict(**value)
            return klass(value)

        parsed_data = {}
        for field_name, field_klass in cls._fields().items():
            try:
                raw_value = data[field_name]
            except KeyError:
                continue

            if getattr(field_klass, '_name', '') == 'List':
                inner_klass = get_args(field_klass)[0]  # TODO: test composite types
                item = [_build(klass=inner_klass, value=i) for i in raw_value]
            elif getattr(field_klass, '_name', '') == 'Dict':
                inner_klass_key, inner_klass_value = get_args(field_klass)
                item = {
                    _build(klass=inner_klass_key, value=k): _build(klass=inner_klass_value, value=v)
                    for k, v in raw_value.items()
                }
            else:
                item = _build(klass=field_klass, value=raw_value)
            parsed_data[field_name] = item

        return cls(**parsed_data)

    def serialize(self) -> Dict:
        return self._to_dict()

    def _to_dict(self) -> dict:
        # TODO handle custom dynamic fields
        def _unbuild(value):
            if value is None:
                return value
            if isinstance(value, EmbeddedDocument):
                return value._to_dict()
            return value

        data = {}
        for field, field_klass in self.__class__._fields().items():
            raw_value = getattr(self, field)

            if getattr(field_klass, '_name', '') == 'List':
                item = [_unbuild(value=i) for i in raw_value]
            elif getattr(field_klass, '_name', '') == 'Dict':
                item = {
                    _unbuild(value=k): _unbuild(value=v)
                    for k, v in raw_value.items()
                }
            else:
                item = _unbuild(value=raw_value)

            data[field] = item

        return data


@dataclass
class Document(EmbeddedDocument):
    @property
    def pk(self) -> str:
        raise NotImplementedError()

    def save(self) -> Document:
        return self.create(**self._to_dict())

    @classmethod
    def _collection_ref(cls) -> CollectionReference:
        return settings.db.collection(cls.collection_name())

    @classmethod
    def collection_name(cls) -> str:
        return cls.__name__.lower()

    @classmethod
    def list(cls, **kwargs) -> Generator[Document]:
        ref = cls._collection_ref()

        for key, value in kwargs.items():
            field, operator = query_operator(key=key)
            # TODO Validate operator, not everything is allowed
            ref = ref.where(field, operator, value)

        for item in ref.stream():
            yield cls._from_dict(**item.to_dict())

    @classmethod
    def get(cls, pk: str) -> Document:
        ref = cls._collection_ref().document(pk).get()
        if ref.exists:
            return cls._from_dict(**ref.to_dict())
        raise DoesNotExist(cls, pk)

    @classmethod
    def create(cls, **kwargs) -> Document:
        data = kwargs.copy()
        obj = cls.deserialize(**data)

        pk = obj.pk
        if not pk:
            raise Exception()
        cls._collection_ref().document(pk).set(obj._to_dict())
        return cls.get(pk=pk)

    @classmethod
    def update(cls, pk: str, **kwargs) -> Document:
        if kwargs:
            # TODO: enable partial nested updates
            as_data = {
                key: value._to_dict() if isinstance(value, EmbeddedDocument) else value
                for key, value in kwargs.items()
            }
            cls._collection_ref().document(pk).set(as_data, merge=True)
        return cls.get(pk=pk)

    @classmethod
    def delete(cls, pk: str) -> None:
        cls._collection_ref().document(pk).delete()


@dataclass
class KeyValueEmbeddedDocument(EmbeddedDocument, ABC):
    key: str
    value: str

    @property
    def as_str(self) -> str:
        return f'{self.key}="{self.value}"'

    @property
    def as_kv(self):
        return f'{self.key}={self.value}'


@dataclass
class Project(EmbeddedDocument):
    id: str
    number: str = None

    @classmethod
    def default(cls) -> Project:
        return cls(
            id=settings.DEFAULT_PROJECT,
        )

    @classmethod
    def default_for_network(cls) -> Project:
        return cls(
            id=settings.DEFAULT_PROJECT_NETWORK,
        )

    def __post_init__(self):
        if not self.number:
            project_info = GoogleResourceManager().get_project(project_id=self.id)
            self.number = project_info['projectNumber']

    @property
    def compute_account(self) -> str:
        return GoogleIAM().get_compute_service_account(project_number=self.number)

    @property
    def cloud_build_account(self) -> str:
        return GoogleIAM().get_cloud_build_service_account(project_number=self.number)

    @property
    def cloud_run_account(self) -> str:
        return GoogleIAM().get_cloud_run_service_account(project_number=self.number)
