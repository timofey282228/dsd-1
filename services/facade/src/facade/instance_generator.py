import asyncio
import logging
import random
from contextlib import AbstractAsyncContextManager
from functools import partial
from typing import Iterable, Optional, Self

from config_server_client import ConfigServerClient, InstanceAddress

logger = logging.getLogger(__name__)


class ServiceInstance(AbstractAsyncContextManager):
    def __init__(
        self,
        generator: RandomInstanceGenerator,
        instance: InstanceAddress,
    ):
        self.instance_generator = generator
        self.instance: InstanceAddress = instance
        self._refresh_on_error_types = ()

    def refreshing_on(self, exceptions: Iterable[type[Exception]]) -> Self:
        self._refresh_on_error_types = tuple(exceptions)
        return self

    async def __aenter__(self) -> InstanceAddress:
        return self.instance

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            return
        if any(map(partial(issubclass, exc_type), self._refresh_on_error_types)):
            # we assume this exception was caused by a faulty instance
            self.instance_generator.refresh.set()
            logger.warning(
                "Caught exception %s, assuming instance %s is not alive",
                exc_type,
                self.instance,
            )

        return await super().__aexit__(exc_type, exc_value, traceback)


class RandomInstanceGenerator:
    def __init__(self, service: str, config_server_client: ConfigServerClient):
        self.service_name = service
        self.config_server = config_server_client
        self.refresh = asyncio.Event()
        self.instances: Optional[list[InstanceAddress]] = None

    async def random_instance(self):
        if self.instances is None or len(self.instances) == 0 or self.refresh.is_set():
            logger.info("Fetching new instances for %s", self.service_name)
            instances = sorted(
                (await self.config_server.get_instances(self.service_name)).root
            )
            if len(instances) > 0:
                self.refresh.clear()
            self.instances = instances

        return ServiceInstance(self, random.choice(self.instances))
