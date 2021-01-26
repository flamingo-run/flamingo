import abc
from collections import defaultdict
from pathlib import Path
from typing import Tuple, Dict, Any, List

import aiofiles
from gcp_pilot.datastore import Document, DoesNotExist
from sanic.request import Request, RequestParameters, File
from sanic.response import json, HTTPResponse
from sanic.views import HTTPMethodView

import exceptions
import settings

PayloadType = Dict[str, Any]
ResponseType = Tuple[PayloadType, int]


class ViewBase(HTTPMethodView):
    model: Document

    @classmethod
    async def write_file(cls, file: File, filepath: Path):
        filepath.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(filepath, 'wb') as f:
            await f.write(file.body)
        await f.close()

    def _parse_query(self, query_args: List[Tuple[str, str]]) -> Dict[str, str]:
        query = {}
        for key, value in query_args:
            if key not in query:
                query[key] = value
            elif isinstance(query[key], list):
                query[key].append(value)
            else:
                query[key] = [query[key], value]

        return query


class ListView(ViewBase):
    async def get(self, request: Request) -> HTTPResponse:
        response = {
            'results': [
                obj.serialize()
                for obj in
                await self.perform_get(query_filters=self._parse_query(request.query_args))
            ]
        }
        return json(response, 200)

    async def perform_get(self, query_filters) -> List[Document]:
        return self.model.documents.filter(**query_filters)

    async def post(self, request: Request) -> HTTPResponse:
        obj = await self.perform_create(data=request.json)
        data = obj.serialize()
        return json(data, 201)

    async def perform_create(self, data: PayloadType) -> Document:
        obj = self.model.deserialize(**data)
        return obj.save()


class DetailView(ViewBase):
    async def get(self, request: Request, pk: str) -> HTTPResponse:
        try:
            obj = self.model.documents.get(id=pk)
        except DoesNotExist as e:
            raise exceptions.NotFoundError() from e

        data = obj.serialize()
        return json(data, 200)

    async def perform_get(self, pk, query_filters) -> Document:
        return self.model.documents.get(id=pk, **query_filters)

    async def put(self, request: Request, pk: str) -> HTTPResponse:
        payload = request.json
        obj = await self.perform_create(data=payload)
        data = obj.serialize()
        return json(data, 200)

    async def perform_create(self, data: PayloadType) -> Document:
        obj = self.model.deserialize(**data)
        return obj.save()

    async def patch(self, request: Request, pk: str) -> HTTPResponse:
        payload = {} if request.files else request.json
        obj = await self.perform_update(pk=pk, data=payload, files=request.files)

        data = obj.serialize()
        return json(data, 200)

    async def perform_update(self, pk: str, data: PayloadType, files: RequestParameters) -> Document:
        obj = self.model.documents.update(pk=pk, **data)

        file_updates: Dict[str, Any] = defaultdict(list)
        for key, file in files.items():
            filepath = await self.store_file(
                obj=obj,
                field_name=key,
                file=file[0],  # TODO: check if it's possible to have more files
            )
            if '__' not in key:
                file_updates[key] = filepath
            else:
                key = key.split('__')[0]
                file_updates[key].append(filepath)
        obj = self.model.documents.update(pk=pk, **file_updates)

        return obj

    async def store_file(self, obj: Document, field_name: str, file: File) -> str:
        local_filepath = settings.STAGE_DIR / 'media' / obj.pk / field_name
        await self.write_file(file=file, filepath=local_filepath)
        return str(local_filepath)

    async def delete(self, request: Request, pk: str) -> HTTPResponse:
        await self.perform_delete(pk=pk)
        return json({}, 204)

    async def perform_delete(self, pk: str) -> None:
        self.model.documents.delete(pk=pk)


class ActionView(ViewBase):
    def get_model(self, pk: str) -> Document:
        return self.model.documents.get(pk=pk)

    async def get(self, request: Request, pk: str) -> HTTPResponse:
        try:
            obj = self.get_model(pk=pk)
        except DoesNotExist as e:
            raise exceptions.NotFoundError() from e

        data, status = await self.perform_get(request=request, obj=obj)
        return json(data, status)

    @abc.abstractmethod
    async def perform_get(self, request: Request, obj: Document) -> ResponseType:
        raise exceptions.NotAllowedError()

    async def post(self, request: Request, pk: str) -> HTTPResponse:
        try:
            obj = self.get_model(pk=pk)
        except DoesNotExist as e:
            raise exceptions.NotFoundError() from e

        data, status = await self.perform_post(request=request, obj=obj)
        return json(data, status)

    @abc.abstractmethod
    async def perform_post(self, request: Request, obj: Document) -> ResponseType:
        raise NotImplementedError()

    async def delete(self, request: Request, pk: str) -> HTTPResponse:
        try:
            obj = self.get_model(pk=pk)
        except DoesNotExist as e:
            raise exceptions.NotFoundError() from e

        data, status = await self.perform_delete(request=request, obj=obj)
        return json(data, status)

    @abc.abstractmethod
    async def perform_delete(self, request: Request, obj: Document) -> ResponseType:
        raise NotImplementedError()
