import abc
from pathlib import Path
from typing import Tuple, Dict, Any

import aiofiles
from sanic.request import Request, RequestParameters, File
from sanic.response import json, HTTPResponse
from sanic.views import HTTPMethodView

import settings
from models.base import Document, DoesNotExist

PayloadType = Dict[str, Any]
ResponseType = Tuple[PayloadType, int]

NotFoundResponse = json({"error": "Not found"}, 404)
NotAllowedResponse = json({'error': "Not allowed"}, 405)


class ViewBase(HTTPMethodView):
    model: Document

    @classmethod
    async def write_file(cls, file: File, filepath: Path):
        filepath.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(filepath, 'wb') as f:
            await f.write(file.body)
        f.close()


class ListView(ViewBase):
    async def get(self, request: Request) -> HTTPResponse:
        response = {
            'results': [obj.serialize() for obj in self.model.list()]
        }
        return json(response, 200)

    async def post(self, request: Request) -> HTTPResponse:
        data, status = await self.perform_create(data=request.json)
        return json(data, status)

    async def perform_create(self, data: PayloadType) -> ResponseType:
        obj = self.model.create(**data)
        return obj.serialize(), 201


class DetailView(ViewBase):
    async def get(self, request: Request, pk: str) -> HTTPResponse:
        try:
            obj = self.model.get(pk=pk)
        except DoesNotExist:
            return NotFoundResponse

        data = obj.serialize()
        return json(data, 200)

    async def put(self, request: Request, pk: str) -> HTTPResponse:
        obj = self.model.create(pk=pk, **request.json)
        return json(obj.serialize(), 200)

    async def patch(self, request: Request, pk: str) -> HTTPResponse:
        payload = {} if request.files else request.json
        data, status = await self.perform_update(pk=pk, data=payload, files=request.files)
        return json(data, status)

    async def perform_update(self, pk: str, data: PayloadType, files: RequestParameters) -> ResponseType:
        obj = self.model.update(pk=pk, **data)

        file_updates = {}
        for key, file in files.items():
            filepath = await self.store_file(
                obj=obj,
                field_name=key,
                file=file[0],  # TODO: check if it's possible to have more files
            )
            file_updates[key] = filepath
        obj = self.model.update(pk=pk, **file_updates)

        return obj.serialize(), 200

    async def store_file(self, obj: Document, field_name: str, file: File) -> str:
        local_filepath = settings.STAGE_DIR / 'media' / obj.pk / field_name
        await self.write_file(file=file, filepath=local_filepath)
        return str(local_filepath)

    async def delete(self, request: Request, pk: str) -> HTTPResponse:
        self.model.delete(pk=pk)
        return json({}, 204)


class ActionView(ViewBase):
    def get_model(self, pk: str) -> Document:
        return self.model.get(pk=pk)

    async def get(self, request: Request, pk: str) -> HTTPResponse:
        try:
            obj = self.get_model(pk=pk)
        except DoesNotExist:
            return NotFoundResponse

        data, status = await self.perform_get(request=request, obj=obj)
        return json(data, status)

    @abc.abstractmethod
    async def perform_get(self, request: Request, obj: Document) -> ResponseType:
        raise NotImplementedError()

    async def post(self, request: Request, pk: str) -> HTTPResponse:
        try:
            obj = self.get_model(pk=pk)
        except DoesNotExist:
            return NotFoundResponse

        data, status = await self.perform_post(request=request, obj=obj)
        return json(data, status)

    @abc.abstractmethod
    async def perform_post(self, request: Request, obj: Document) -> ResponseType:
        raise NotImplementedError()

    async def delete(self, request: Request, pk: str) -> HTTPResponse:
        try:
            obj = self.get_model(pk=pk)
        except DoesNotExist:
            return NotFoundResponse

        data, status = await self.perform_delete(request=request, obj=obj)
        return json(data, status)

    @abc.abstractmethod
    async def perform_delete(self, request: Request, obj: Document) -> ResponseType:
        raise NotImplementedError()
