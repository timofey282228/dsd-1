import logging
import logging.config
from abc import ABCMeta
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Annotated

import pydantic
from config_server_client import ConfigServerClient
from fastapi import Body, FastAPI, Request
from hazelcast.client import HazelcastClient
from hazelcast.config import Config as HazelcastConfig
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo.asynchronous.mongo_client import AsyncMongoClient

SERVICE_NAME = "counter"
SERVICE_PORT = 80
HEALTHCHECK_PATH = "/health"


logger = logging.getLogger(__name__)


#  MARK: models

type UserId = int


class Transaction(pydantic.BaseModel):
    amount: int


class UserBalance(pydantic.BaseModel):
    balance: int


class AllUserBalances(pydantic.RootModel):
    root: dict[UserId, int]


class AddTransactionMessage(pydantic.BaseModel):
    user_id: UserId
    transaction_request: Transaction


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_prefix="COUNTER_",
        env_prefix_target="alias",
        validate_default=True,
    )
    mongodb_connection_string: pydantic.MongoDsn = pydantic.Field(
        alias="MONGODB_CONNECTION_STRING"
    )
    hazelcast_cluster: str = pydantic.Field(alias="HAZELCAST_CLUSTER")
    hazelcast_cluster_members: list[str] = pydantic.Field(
        default=["127.0.0.1", "hazelcast"], alias="HAZELCAST_CLUSTER_MEMBERS"
    )
    config_server_netloc: str = pydantic.Field(alias="CONFIGSERVER_NETLOC")


#  MARK: API


class ApiState(Mapping, metaclass=ABCMeta):
    counter: AbstractCounter
    mongodb: AsyncMongoClient
    config: Config


@asynccontextmanager
async def api_lifespan(_: FastAPI):
    service_config = Config()
    config_server_client = ConfigServerClient(service_config.config_server_netloc)

    hz_config = HazelcastConfig()
    hz_config.client_name = "counter"
    hz_config.cluster_name = service_config.hazelcast_cluster
    hz_config.cluster_members = ["hazelcast"]

    hz_client = HazelcastClient(config=hz_config)

    await config_server_client.register(SERVICE_NAME, SERVICE_PORT, HEALTHCHECK_PATH)

    async with AsyncMongoClient(
        service_config.mongodb_connection_string.encoded_string(),
        uuidRepresentation="standard",
    ) as mongodb_client:
        counter = MongoCounter(collection=mongodb_client["microservices"]["counter"])
        logger.debug("Creating CounterQueueListener instance...")
        queue_listener = CounterQueueListener(counter, hz_client)
        await queue_listener.start()

        yield {
            "counter": MongoCounter(
                collection=mongodb_client["microservices"]["counter"]
            ),
            "mongodb": mongodb_client,
            "config": service_config,
            "queue_listener": queue_listener,
        }

        queue_listener.shutdown()

    await config_server_client.unregister(SERVICE_NAME, SERVICE_PORT)
    hz_client.shutdown()


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

# MARK: POST


@api.post("/users/{user_id}")
async def post_balance(
    request: Request,
    user_id: UserId,
    transaction: Annotated[Transaction, Body()],
) -> UserBalance:
    request: Request[ApiState] = request  # type: ignore[no-redef]
    balance = await request.state.counter.execute_transaction(
        user_id=user_id,
        transaction=transaction,
    )
    return UserBalance(balance=balance)


# MARK: GET


@api.get("/users/{user_id}")
async def get_balance(
    request: Request,
    user_id: UserId,
) -> UserBalance:
    request: Request[ApiState] = request  # type: ignore[no-redef]
    return UserBalance(
        balance=await request.state.counter.get_balance(user_id=user_id),
    )


@api.get("/users")
async def get_all_balances(
    request: Request,
) -> AllUserBalances:
    request: Request[ApiState] = request  # type: ignore[no-redef]
    return AllUserBalances(await request.state.counter.get_balances())


@api.get(HEALTHCHECK_PATH)
async def health():
    return True


from .abstract_counter import AbstractCounter
from .counter_queue_listener import CounterQueueListener
from .mongo_counter import MongoCounter
