#!/usr/bin/env bash
# demonstration script interacting with the microservices

# post_amount <user_id> <amount>
post_amount() {
    curl --silent \
        "$FACADE_BASE_URL/users/$1/amount" \
        -X POST \
        --json '{"amount":'"$2"'}' \
        | jq .
}

# get_balances
get_balances() {
    curl --silent \
        "$FACADE_BASE_URL/balances" \
        | jq -S .
}

# get_user_statement <user_id>
get_user_statement() {
    curl --silent \
    "$FACADE_BASE_URL/users/$1" \
    | jq .
}

PS4=""
FACADE_BASE_URL="http://localhost:$(docker compose port facade 80 | cut -d: -f2)"
set -x
post_amount 1 10
post_amount 1 25
post_amount 2 100
get_user_statement 1
get_balances
