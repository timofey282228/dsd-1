# Microservices basics (lab 1)

## Architecture

```mermaid
architecture-beta
    group lab1(cloud)[Microservices basics]

    service facade(server)[facade] in lab1
    service counter(database)[counter] in lab1
    service logging(disk)[logging] in lab1

   facade:L <--> T:counter
   facade:R <--> T:logging
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
├── pyproject.toml        # shared dependencies, can use with client.py e.g. via `poetry shell` 
├── services              # service implementations
│   ├── countersvc
│   ├── facade
│   └── logsvc
└── stats.py              # Count averages from scenario CSV
```
