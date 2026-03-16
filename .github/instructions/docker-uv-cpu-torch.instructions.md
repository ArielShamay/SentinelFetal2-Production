---
description: 'Docker + uv + CPU-only PyTorch safeguards for SentinelFetal2 backend images.'
applyTo: 'Dockerfile,docker-compose.yml,docs/docker_guide.md,README.md,**/*.dockerfile'
---

# Docker migration safeguards

## Scope
This file applies to uv migration workflow work only.
Do not treat it as default policy for unrelated repository tasks.

## Context
This repository previously installed `torch` from generic indexes in Docker, which can pull GPU-related packages and inflate image size.
The migration target is uv-managed dependencies with CPU-oriented PyTorch defaults unless GPU is explicitly requested.

## Required Docker principles
- Use uv for dependency sync inside image build stages.
- Preserve layer caching by separating dependency sync from source copy where possible.
- Keep `.venv` out of build context.
- Keep runtime image minimal and deterministic.

## PyTorch policy
- Configure PyTorch indexes via uv project metadata (`tool.uv.sources` + `[[tool.uv.index]]`) when CPU pinning is required.
- Prefer explicit index entries and `explicit = true` for PyTorch-specific indexes.
- Avoid accidental fallback that introduces CUDA packages in CPU-target images.

## Build behavior
- Build must fail fast when required artifacts are missing (retain or improve existing artifact validation gate).
- Runtime command should execute in the uv-managed environment (`uv run ...` or equivalent PATH to `.venv/bin`).

## Compose behavior
- Keep persistent mounts for data/weights/logs as needed.
- Preserve healthcheck semantics.
- Do not introduce dependency install steps at container startup.

## Documentation behavior
- Docker instructions must explain uv-native lifecycle clearly:
  - lock/sync first
  - deterministic build
  - no pip-first fallback
