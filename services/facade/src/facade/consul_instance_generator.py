import asyncio
from typing import Any

from consul import Consul

from .abstract_random_instance_generator import AbstractRandomInstanceGenerator


class ConsulRandomInstanceGenerator(AbstractRandomInstanceGenerator):

    def __init__(self, service: str, consul: Consul):
        self.consul = consul
        self._service_name = service
        self._refresh = asyncio.Event()
        self._instances = None

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
        return list(
            map(
                lambda s: (s["Service"]["Address"], s["Service"]["Port"]),
                self.consul.health.service(self.service_name, passing=True)[1],
            )
        )
