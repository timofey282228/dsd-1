import datetime
from abc import ABCMeta
from collections.abc import Mapping
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pydantic
from config_server_client import ConfigServerClient
from fastapi import FastAPI, Request
from hazelcast.asyncio import HazelcastClient
from hazelcast.config import Config as HazelcastConfig
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "logging"
SERVICE_PORT = 80
HEALTHCHECK_PATH = "/health"

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
    hazelcast_cluster: str = pydantic.Field(alias="HAZELCAST_CLUSTER")
    hazelcast_cluster_members: list[str] = pydantic.Field(
        default=["127.0.0.1", "hazelcast"], alias="HAZELCAST_CLUSTER_MEMBERS"
    )
    config_server_netloc: str = pydantic.Field(alias="CONFIGSERVER_NETLOC")


#  MARK: API


class ApiState(Mapping, metaclass=ABCMeta):
    logging: AbstractLogging
    config: Config


@asynccontextmanager
async def api_lifespan(_: FastAPI):
    service_config = Config()
    config_server_client = ConfigServerClient(service_config.config_server_netloc)

    hz_config = HazelcastConfig()
    hz_config.client_name = "logsvc"
    hz_config.cluster_name = service_config.hazelcast_cluster
    hz_config.cluster_members = ["hazelcast"]

    hz_client = await HazelcastClient.create_and_start(config=hz_config)

    await config_server_client.register(SERVICE_NAME, SERVICE_PORT, HEALTHCHECK_PATH)

    yield {
        "config": service_config,
        # "logging": MemoryLogging()
        "logging": await HazelcastLogging.from_hz_client(hz_client),
    }

    await config_server_client.unregister(SERVICE_NAME, SERVICE_PORT)
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
