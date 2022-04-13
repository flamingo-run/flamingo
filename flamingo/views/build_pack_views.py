from typing import Dict

from sanic import Blueprint
from sanic.request import File
from sanic_rest.views import DetailView, ListView, PayloadType

from models.buildpack import BuildPack

build_packs = Blueprint('build-packs', url_prefix='/build-packs')


class BuildPackListView(ListView):
    model = BuildPack

    async def perform_create(self, data: PayloadType, files: Dict[str, File]) -> BuildPack:
        obj = await super().perform_create(data=data, files=files)
        return obj


class BuildPackDetailView(DetailView):
    model = BuildPack

    async def store_file(self, obj: BuildPack, field_name: str, file: File) -> str:
        # TODO: Optimize to upload from memory
        await self.write_file(file=file, filepath=obj.local_dockerfile)
        gcs_url = await obj.upload_dockerfile()
        obj.dockerfile_url = gcs_url
        obj.save()
        return gcs_url


build_packs.add_route(BuildPackListView.as_view(), '/')
build_packs.add_route(BuildPackDetailView.as_view(), '/<pk>')
