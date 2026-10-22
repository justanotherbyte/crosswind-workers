"""The Images binding. `hosted`, for stored images, passes through."""

from typing import Any

from ..response import Response
from ..rpc import python_from_rpc, python_to_rpc
from .base import Binding, _js_options

__all__ = ("ImageTransformationResult", "ImageTransformer", "ImagesBinding")


class ImageTransformationResult(Binding):
    def response(self) -> Response:
        return Response(self.js_object.response())

    def content_type(self) -> str:
        return self.js_object.contentType()

    def image(
        self, options: Any = None, *, encoding: str | None = None, **extra: Any
    ) -> Any:
        return self.js_object.image(_js_options(options, extra, encoding=encoding))


class ImageTransformer(Binding):
    def transform(self, transform: Any = None, /, **options: Any) -> "ImageTransformer":
        # The transform names, such as width and fit, are single JS words.
        return ImageTransformer(
            self.js_object.transform(_js_options(transform, options))
        )

    def draw(
        self, image: Any, options: Any = None, /, **extra: Any
    ) -> "ImageTransformer":
        js_image = python_to_rpc(image)
        return ImageTransformer(
            self.js_object.draw(js_image, _js_options(options, extra))
        )

    async def output(
        self,
        options: Any = None,
        *,
        format: str | None = None,
        quality: int | None = None,
        **extra: Any,
    ) -> ImageTransformationResult:
        js_options = _js_options(options, extra, format=format, quality=quality)
        return ImageTransformationResult(await self.js_object.output(js_options))


class ImagesBinding(Binding):
    async def info(
        self, stream: Any, options: Any = None, /, **extra: Any
    ) -> dict[str, Any]:
        js_options = _js_options(options, extra)
        return python_from_rpc(await self.js_object.info(stream, js_options))

    def input(
        self, stream: Any, options: Any = None, /, **extra: Any
    ) -> ImageTransformer:
        return ImageTransformer(
            self.js_object.input(stream, _js_options(options, extra))
        )
