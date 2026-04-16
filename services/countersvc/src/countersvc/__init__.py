import logging
import logging.config
import random
import socket
import string
from abc import ABCMeta
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Annotated, Optional, Self

import pydantic
from consul import Check, Consul
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
    counter: AbstractCounter
    mongodb: AsyncMongoClient
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
    hz_config.client_name = SERVICE_NAME
    hz_config.cluster_name = consul_config.hazelcast_cluster_name
    hz_config.cluster_members = consul_config.hazelcast_cluster_members

    hz_client = HazelcastClient(config=hz_config)

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

    async with AsyncMongoClient(
        service_config.mongodb_connection_string.encoded_string(),
        uuidRepresentation="standard",
    ) as mongodb_client:
        counter = MongoCounter(collection=mongodb_client["microservices"]["counter"])
        logger.debug("Creating CounterQueueListener instance...")
        queue_listener = CounterQueueListener(
            counter, hz_client, consul_config.counter_hazelcast_queue_name
        )
        await queue_listener.start()

        yield {
            "counter": MongoCounter(
                collection=mongodb_client["microservices"]["counter"]
            ),
            "mongodb": mongodb_client,
            "config": service_config,
            "queue_listener": queue_listener,
        }
        consul.agent.service.deregister(
            consul_service_id, token=service_config.consul_token
        )
        queue_listener.shutdown()

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
