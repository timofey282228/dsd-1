import asyncio
import logging
from typing import Optional

from config_server_client import ConfigServerClient, InstanceAddress

from .abstract_random_instance_generator import AbstractRandomInstanceGenerator

logger = logging.getLogger(__name__)


class ConfigServerRandomInstanceGenerator(
    AbstractRandomInstanceGenerator[InstanceAddress]
):
    def __init__(self, service: str, config_server_client: ConfigServerClient):
        self.config_server = config_server_client
        self._service_name = service
        self._refresh = asyncio.Event()
        self._instances: Optional[list[InstanceAddress]] = None

    @property
    def service_name(self):
        return self._service_name

    @property
    def instances(self):
        return self._instances

    @instances.setter
    def instances(self, value):
        self._instances = value

    @property
    def refresh(self):
        return self._refresh

    async def get_instances(self):
        return (await self.config_server.get_instances(self.service_name)).root
