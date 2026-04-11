from abc import ABCMeta
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Annotated

import pydantic
from fastapi import Body, FastAPI, Request
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo.asynchronous.mongo_client import AsyncMongoClient

#  MARK: models

type UserId = int


class Transaction(pydantic.BaseModel):
    amount: int


class UserBalance(pydantic.BaseModel):
    balance: int


class AllUserBalances(pydantic.RootModel):
    root: dict[UserId, int]


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


#  MARK: API


class ApiState(Mapping, metaclass=ABCMeta):
    counter: AbstractCounter
    mongodb: AsyncMongoClient
    config: Config


@asynccontextmanager
async def api_lifespan(_: FastAPI):
    service_config = Config()
    async with AsyncMongoClient(
        service_config.mongodb_connection_string.encoded_string(),
        uuidRepresentation="standard",
    ) as mongodb_client:
        yield {
            "counter": MongoCounter(
                collection=mongodb_client["microservices"]["counter"]
            ),
            "mongodb": mongodb_client,
            "config": service_config,
        }


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


from .abstract_counter import AbstractCounter
from .mongo_counter import MongoCounter
