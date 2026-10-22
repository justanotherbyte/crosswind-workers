from collections.abc import Iterable
from typing import Any

from ..rpc import python_from_rpc, python_to_rpc
from .base import Binding, _js_options

__all__ = ("Vectorize",)


class Vectorize(Binding):
    async def describe(self) -> dict[str, Any]:
        return python_from_rpc(await self.js_object.describe())

    async def query(
        self,
        vector: list[float] | Any,
        options: Any = None,
        /,
        *,
        top_k: int | None = None,
        namespace: str | None = None,
        return_values: bool | None = None,
        return_metadata: bool | str | None = None,
        filter: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        js_options = _js_options(
            options,
            extra,
            top_k=top_k,
            namespace=namespace,
            return_values=return_values,
            return_metadata=return_metadata,
            filter=filter,
        )
        matches = await self.js_object.query(python_to_rpc(vector), js_options)
        return python_from_rpc(matches)

    async def query_by_id(
        self,
        vector_id: str,
        options: Any = None,
        /,
        *,
        top_k: int | None = None,
        namespace: str | None = None,
        return_values: bool | None = None,
        return_metadata: bool | str | None = None,
        filter: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        js_options = _js_options(
            options,
            extra,
            top_k=top_k,
            namespace=namespace,
            return_values=return_values,
            return_metadata=return_metadata,
            filter=filter,
        )
        return python_from_rpc(await self.js_object.queryById(vector_id, js_options))

    async def insert(self, vectors: Iterable[dict[str, Any]]) -> dict[str, Any]:
        return python_from_rpc(
            await self.js_object.insert(python_to_rpc(list(vectors)))
        )

    async def upsert(self, vectors: Iterable[dict[str, Any]]) -> dict[str, Any]:
        return python_from_rpc(
            await self.js_object.upsert(python_to_rpc(list(vectors)))
        )

    async def delete_by_ids(self, ids: Iterable[str]) -> dict[str, Any]:
        return python_from_rpc(
            await self.js_object.deleteByIds(python_to_rpc(list(ids)))
        )

    async def get_by_ids(self, ids: Iterable[str]) -> list[dict[str, Any]]:
        return python_from_rpc(await self.js_object.getByIds(python_to_rpc(list(ids))))
