# Microservices basics (lab 1)

## Architecture

```mermaid
architecture-beta
    group lab1(cloud)[Microservices basics]
    group lab3(server)[Microservices Hazelcast]

    service facade(server)[facade] in lab1
    service counter(database)[counter] in lab1
    service logging(disk)[logging] in lab1

    service mongodb(disk)[MongoDB] in lab3
    service hazelcast(disk)[Hazelcast] in lab3

   facade:L <--> B:counter
   facade:R <--> B:logging
   hazelcast:B <--> T:logging
   mongodb:B <--> T:counter
```

## Structure

Most importantly:

```text
.
├── client.py             # client script
├── demo.sh               # used for functionality demo in report
├── docker-bake.hcl       # alternative to compose build
├── docker-compose.yaml
├── Dockerfile
├── dsd1client.sh         # shell client function
├── .env.example          # example .env with required vars 
├── pyproject.toml        # shared dependencies, can use with client.py e.g. via `poetry shell` 
├── services              # service implementations
│   ├── countersvc
│   ├── facade
│   └── logsvc
└── stats.py              # Count averages from scenario CSV
```
