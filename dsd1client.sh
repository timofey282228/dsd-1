#!/usr/bin/env bash

dsd1client() {
    local endpoint="${1##*(/)}"
    if (($# == 1)); then
        curl --silent "http://localhost:$(docker compose port facade 80 | cut -d: -f2)/$endpoint" \
        | jq .
    elif (($# == 2)); then
        curl --silent "http://localhost:$(docker compose port facade 80 | cut -d: -f2)/$endpoint" \
            -X POST \
            --json "$2" \
            | jq .
    else
        return 1
    fi
}
