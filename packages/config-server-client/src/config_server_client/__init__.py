import logging
from typing import Optional

import httpx
import pydantic
from httpx import URL

logger = logging.getLogger(__name__)


class ServiceInstances(pydantic.RootModel):
    root: set[tuple[str, int]]


class ConfigServerClient:
    def __init__(self, netloc: bytes | str):
        url = URL(
            scheme="http",
            netloc=netloc if isinstance(netloc, bytes) else netloc.encode(),
        )
        self.url = url
        self.http_client = httpx.AsyncClient(base_url=url)

    async def register(
        self, name: str, port: int, healthcheck_path: Optional[str] = None
    ):
        logger.debug("Register %s port %s at %s", name, port, self.url)
        path = f"/services/{name}?port={port}"
        if healthcheck_path is not None:
            path += "&healthcheck_path=" + healthcheck_path

        response = await self.http_client.put(path)
        response.raise_for_status()

    async def get_instances(self, service: str) -> ServiceInstances:
        response = await self.http_client.get(f"/services/{service}")
        instances = ServiceInstances.model_validate_json(response.content)
        return instances

    async def unregister(self, name: str, port: int):
        await self.http_client.delete(f"/services/{name}?port={port}")
