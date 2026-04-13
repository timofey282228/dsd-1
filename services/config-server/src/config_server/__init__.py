import asyncio
import itertools
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Iterable, Optional

import annotated_types
import fastapi.responses
import httpx
import pydantic
from fastapi import FastAPI, Request
from pydantic import RootModel
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


@dataclass(eq=True, frozen=True)
class ServiceInstance:
    host: str
    port: int
    healthcheck_path: Optional[str] = None

    async def health_check(self) -> bool:
        if (healthcheck_path := self.healthcheck_path) is None:
            return True

        async with httpx.AsyncClient(
            base_url=httpx.URL(scheme="http", host=self.host, port=self.port)
        ) as http_client:
            try:
                healthcheck_response = await http_client.get(healthcheck_path)
                if healthcheck_response.status_code == httpx.codes.OK:
                    return True
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
            ):  # expected if service is not available
                pass
            except Exception as e:
                logger.exception("Health check exception for %s", self, exc_info=e)
        return False


async def check_instances(
    instances: Iterable[ServiceInstance],
) -> tuple[set[ServiceInstance], set[ServiceInstance]]:

    async def _instance_healthcheck(
        instance: ServiceInstance,
    ) -> tuple[bool, ServiceInstance]:
        return await instance.health_check(), instance

    reachable_instances = set()
    unreachable_instances = set()

    async for instance_health_check in asyncio.as_completed(
        asyncio.create_task(_instance_healthcheck(instance)) for instance in instances
    ):
        available, instance = await instance_health_check
        if available:
            reachable_instances.add(instance)
        else:
            unreachable_instances.add(instance)

    return reachable_instances, unreachable_instances


class ServiceRegistry:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.reachable_instances: defaultdict[str, set[ServiceInstance]] = defaultdict(
            set
        )
        self.unreachable_instances: defaultdict[str, set[ServiceInstance]] = (
            defaultdict(set)
        )

    async def register(
        self,
        service: str,
        service_instance: ServiceInstance,
    ):
        async with self.lock:
            self.reachable_instances[service].add(service_instance)

    async def services(self):
        async with self.lock:
            return set(
                itertools.chain(
                    self.reachable_instances.keys(), self.unreachable_instances.keys()
                )
            )

    async def get_reachable_instances(
        self, service: str
    ) -> Optional[set[ServiceInstance]]:
        async with self.lock:
            if (
                service in self.reachable_instances
                or service in self.unreachable_instances
            ):
                return self.reachable_instances[service]

    async def get_unreachable_instances(
        self, service: str
    ) -> Optional[set[ServiceInstance]]:
        async with self.lock:
            if (
                service in self.reachable_instances
                or service in self.unreachable_instances
            ):
                return self.unreachable_instances[service]

    async def get_instances(self, service: str) -> set[ServiceInstance]:
        instances = set()
        async with self.lock:
            instances.update(self.reachable_instances.get(service, ()))
            instances.update(self.unreachable_instances.get(service, ()))
        return instances

    async def remove_instance(self, service: str, host: str, port: int):
        async with self.lock:
            reachable_instances = self.reachable_instances.get(service) or set()
            to_remove = set()
            for instance in filter(
                lambda instance: instance.host == host and instance.port == port,
                reachable_instances,
            ):
                to_remove.add(instance)

            unreachable_instances = self.unreachable_instances.get(service) or set()
            for instance in filter(
                lambda instance: instance.host == host and instance.port == port,
                unreachable_instances,
            ):
                to_remove.remove(instance)

            reachable_instances -= to_remove
            unreachable_instances -= to_remove


@dataclass
class ServiceConfig:
    max_instances: Optional[int] = None


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_prefix="CONFIGSERVER_",
        env_prefix_target="alias",
        validate_default=True,
    )
    services_configs: Optional[dict[str, ServiceConfig]] = pydantic.Field(
        default=None, alias="SERVICES_CONFIGS"
    )


class ServiceRegistryMonitor:
    def __init__(
        self,
        service_registry: ServiceRegistry,
        services_configs: Optional[dict[str, ServiceConfig]] = None,
    ):
        self.service_registry = service_registry
        self.services_configs = services_configs if services_configs is not None else {}

    async def refresh_service(self, service: str):
        logger.info('Service registry monitor refreshing "%s"', service)
        instances = await self.service_registry.get_instances(service)
        reachable, unreachable = await check_instances(instances)
        if (len_unreachable := len(unreachable)) > 0:
            logger.warning(
                "Service %s has unreachable instances %s", service, unreachable
            )
        async with self.service_registry.lock:
            self.service_registry.reachable_instances[service] = reachable
            if (service_config := self.services_configs.get(service)) is not None:
                if (max_instances := service_config.max_instances) is not None:
                    # if we have more than max reachable instances, then unreachable are probably dead and gone
                    if (
                        len_reachable := len(reachable)
                    ) >= max_instances and len_unreachable > 0:
                        logger.info(
                            'Service "%s" has %s instances - more than max %s all reachable, pruning unreachables',
                            service,
                            len_reachable + len_unreachable,
                            max_instances,
                        )
                        unreachable.clear()
            self.service_registry.unreachable_instances[service] = unreachable

    async def run(self):
        service_sorted_i = 0
        while True:
            await asyncio.sleep(5)
            services = sorted(await self.service_registry.services())
            if (len_services := len(services)) == 0:
                continue
            await self.refresh_service(services[service_sorted_i % len_services])
            service_sorted_i = (service_sorted_i + 1) % len_services


@asynccontextmanager
async def api_lifespan(_: FastAPI):
    config = Config()
    service_registry = ServiceRegistry()
    registry_monitor = ServiceRegistryMonitor(
        service_registry=service_registry, services_configs=config.services_configs
    )
    registry_monitor_task = asyncio.create_task(
        registry_monitor.run(), name="service registry monitor"
    )
    registry_monitor_task.add_done_callback(
        lambda task: logger.warning("Monitor finished %s", task)
    )

    yield {
        "service_registry": service_registry,
    }

    registry_monitor_task.cancel()


logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
        },
        "root": {
            "handlers": ["default"],
            "level": logging.WARNING,
        },
        "loggers": {
            __name__: {
                "level": logging.DEBUG,
            }
        },
    }
)
api = FastAPI(lifespan=api_lifespan)

type InetPort = Annotated[int, annotated_types.Gt(0), annotated_types.Lt(2**16)]


@api.put("/services/{service}", response_class=fastapi.responses.PlainTextResponse)
async def put_service_instance(
    request: Request,
    service: str,
    port: InetPort,
    healthcheck_path: Optional[str] = None,
):
    service_registry: ServiceRegistry = request.state.service_registry
    host = request.client.host
    logger.info('Request to add "%s" instance (%s:%s)', service, host, port)
    await service_registry.register(
        service,
        ServiceInstance(
            host=host,
            port=port,
            healthcheck_path=healthcheck_path,
        ),
    )


@api.delete("/services/{service}")
async def delete_service_instance(
    request: Request,
    service: str,
    port: InetPort,
):
    service_registry: ServiceRegistry = request.state.service_registry
    host = request.client.host
    logger.info("Requesting remove service %s instance %s:%s", service, host, port)
    await service_registry.remove_instance(service, host=host, port=port)


@api.get("/services")
async def get_services(request: Request):
    return tuple(await request.state.service_registry.services())


@api.get("/services/{service}/reachable")
async def get_services(request: Request, service: str):
    return tuple(await request.state.service_registry.get_reachable_instances(service))


@api.get("/services/{service}/unreachable")
async def get_services(request: Request, service: str):
    return tuple(
        await request.state.service_registry.get_unreachable_instances(service)
    )


class GetInstancesResponse(RootModel):
    root: list[tuple[str, int]]


@api.get("/services/{service}")
async def get_instances(request: Request, service: str):
    service_registry: ServiceRegistry = request.state.service_registry
    return GetInstancesResponse(
        map(
            lambda service_instance: (service_instance.host, service_instance.port),
            await service_registry.get_reachable_instances(service) or (),
        )
    )


@api.get("/health")
async def health():
    return True
