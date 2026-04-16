import datetime
import logging
import random
import socket
import string
from abc import ABCMeta
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Optional, Self
from uuid import UUID

import pydantic
from consul import Check, Consul
from fastapi import FastAPI, Request
from hazelcast.asyncio import HazelcastClient
from hazelcast.config import Config as HazelcastConfig
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "logging"
SERVICE_PORT = 80
HEALTHCHECK_PATH = "/health"


logger = logging.getLogger(__name__)
#  MARK: models

type UserId = int


class TransactionData(pydantic.BaseModel):
    user_id: UserId
    amount: int
    timestamp: datetime.datetime


class Transaction(TransactionData):
    transaction_id: UUID


class TransactionList(pydantic.RootModel):
    root: list[Transaction]


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_prefix="LOGGING_",
        env_prefix_target="alias",
        validate_default=True,
    )
    consul_host: Optional[str] = pydantic.Field(default=None, alias="CONSUL_HOST")
    consul_port: Optional[int] = pydantic.Field(default=None, alias="CONSUL_PORT")
    consul_token: Optional[str] = pydantic.Field(default=None, alias="CONSUL_TOKEN")


class ConsulConfig(pydantic.BaseModel):
    hazelcast_cluster_name: str
    hazelcast_cluster_members: list[str]
    counter_hazelcast_queue_name: str

    @classmethod
    def query(cls, consul: Consul) -> Self:
        return cls(
            hazelcast_cluster_name=consul.kv.get("hazelcast_cluster_name")[1][
                "Value"
            ].decode(),
            counter_hazelcast_queue_name=consul.kv.get("counter_hazelcast_queue_name")[
                1
            ]["Value"].decode(),
            hazelcast_cluster_members=pydantic.TypeAdapter(list[str]).validate_json(
                consul.kv.get("hazelcast_cluster_members")[1]["Value"]
            ),
        )


#  MARK: API


class ApiState(Mapping, metaclass=ABCMeta):
    logging: AbstractLogging
    config: Config


@asynccontextmanager
async def api_lifespan(_: FastAPI):
    service_config = Config()
    consul = Consul(
        host=service_config.consul_host,
        port=service_config.consul_port,
        token=service_config.consul_token,
    )
    consul_config = ConsulConfig.query(consul)

    hz_config = HazelcastConfig()
    hz_config.client_name = "logsvc"
    hz_config.cluster_name = consul_config.hazelcast_cluster_name
    hz_config.cluster_members = consul_config.hazelcast_cluster_members

    hz_client = await HazelcastClient.create_and_start(config=hz_config)

    consul_service_id = (
        SERVICE_NAME + "-" + "".join(random.sample(string.ascii_uppercase, 7))
    )
    consul_service_address = socket.gethostbyname(socket.gethostname())
    logger.info("Registering with Consul server as %s", consul_service_id)
    assert consul.agent.service.register(
        name=SERVICE_NAME,
        service_id=consul_service_id,
        address=consul_service_address,
        port=SERVICE_PORT,
        token=service_config.consul_token,
        check=Check.http(
            url=f"http://{consul_service_address}:{SERVICE_PORT}{HEALTHCHECK_PATH}",
            interval="5s",
            timeout="2s",
            deregister="15s",
        ),
    ), "Consul service must be registered successfully"

    yield {
        "config": service_config,
        # "logging": MemoryLogging()
        "logging": await HazelcastLogging.from_hz_client(hz_client),
    }

    consul.agent.service.deregister(
        consul_service_id, token=service_config.consul_token
    )
    await hz_client.shutdown()


api = FastAPI(lifespan=api_lifespan)

# MARK: POST


@api.post("/transactions/{transaction_id}")
async def post_transaction(
    request: Request,
    transaction_id: UUID,
    transaction_data: TransactionData,
):
    request: Request[ApiState] = request  # type: ignore[no-redef]
    await request.state.logging.add_transaction(
        transaction_id=transaction_id,
        transaction_data=transaction_data,
    )


# MARK: GET


@api.get("/users/{user_id}/transactions")
async def get_transactions(
    request: Request,
    user_id: UserId,
) -> TransactionList:
    request: Request[ApiState] = request  # type: ignore[no-redef]
    return await request.state.logging.get_user_transactions(user_id=user_id)


@api.get(HEALTHCHECK_PATH)
async def health():
    return True


from .abstract_logging import AbstractLogging
from .hazelcast_logging import HazelcastLogging
