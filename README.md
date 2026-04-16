# Microservices

## Architecture

```mermaid
architecture-beta
    group lab1(cloud)[Microservices basics]
    group lab3(server)[Microservices Hazelcast]
    group lab4(server)[Microservices MQ]

    service facade(server)[facade] in lab1
    service counter(database)[counter] in lab1
    service logging(disk)[logging] in lab1

    service mongodb(disk)[MongoDB] in lab3
    service hazelcast(disk)[Hazelcast] in lab3

    service configserver(disk)[config server] in lab4

    mongodb:T <--> R:counter

    facade:L <--> R:logging

    hazelcast:T <-- B:facade
    hazelcast:L <--> B:logging
    hazelcast:R --> B:counter

    configserver:B --> T:facade
    configserver:R <-- T:counter
    configserver:L <-- T:logging

```

## Structure

Most importantly:

```text
.
├── client.py                   # client script
├── demo.sh                     # used for functionality demo in report
├── docker-bake.hcl             # alternative to compose build
├── docker-compose.yaml
├── Dockerfile
├── dsd1client.sh               # shell client function
├── .env.example                # example .env with required vars 
├── packages                    # shared dependencies of services
│   └── config-server-client    # custom config server client
├── pyproject.toml              # shared dev dependencies
├── services                    # service implementations
│   ├── config-server           # custom config server
│   ├── countersvc
│   ├── facade
│   └── logsvc
└── stats.py                    # Count averages from scenario CSV
```
