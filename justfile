default:
    @.tools/just --justfile justfile --working-directory . --list

dev:
    docker compose up

dev-build:
    docker compose up --build

dev-down:
    docker compose down --remove-orphans

prod:
    docker compose -f docker-compose.prod.yml up -d

prod-build:
    docker compose -f docker-compose.prod.yml up --build -d

prod-down:
    docker compose -f docker-compose.prod.yml down --remove-orphans
