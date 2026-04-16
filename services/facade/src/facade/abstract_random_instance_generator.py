import asyncio
import logging
import random
from abc import ABCMeta, abstractmethod
from contextlib import AbstractAsyncContextManager
from functools import partial
from typing import Iterable, Optional, Self

logger = logging.getLogger(__name__ + ".services")


class ServiceInstance[InstanceAddress](AbstractAsyncContextManager):
    def __init__(
        self,
        generator: AbstractRandomInstanceGenerator,
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


class AbstractRandomInstanceGenerator(metaclass=ABCMeta):
    type InstanceAddress = tuple[str, int]
    type ServiceInstances = Iterable[InstanceAddress]

    @property
    @abstractmethod
    def service_name(self) -> str: ...

    @property
    @abstractmethod
    def refresh(self) -> asyncio.Event: ...

    @property
    @abstractmethod
    def instances(self) -> Optional[list[InstanceAddress]]: ...

    @abstractmethod
    async def get_instances() -> ServiceInstances:
        """Get instances by querying the config server"""
        ...

    async def random_instance(self) -> ServiceInstance[InstanceAddress]:
        if self.instances is None or len(self.instances) == 0 or self.refresh.is_set():
            logger.info("Fetching new instances for %s", self.service_name)
            instances = sorted(await self.get_instances())
            if len(instances) > 0:
                self.refresh.clear()
            self.instances = instances

        return ServiceInstance(self, random.choice(self.instances))
