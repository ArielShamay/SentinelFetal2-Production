# Dependency bucketing playbook

## Runtime bucket (`project.dependencies`)
Include packages directly required to run production paths:
- API service runtime
- inference/model loading
- production-executed scripts

## Dev bucket (`dependency-groups`)
Include tools for local development and CI quality gates:
- test frameworks
- linters/formatters
- static analysis tooling

## Optional bucket (`project.optional-dependencies`)
Use when functionality is real but non-baseline:
- legacy UI stacks not on default path
- accelerator-specific variants
- integration-only extras

## Rules
- Do not place runtime imports in dev-only groups.
- Avoid duplicate declaration of same package across incompatible buckets unless justified.
- Keep Python compatibility explicit (`requires-python`).
- Prefer explicit torch index/source controls when CPU baseline is required.
- Final Python/dependency decision must be proven by successful lock + virtual-environment sync + runtime verification (not metadata-only).
- Final supported state is uv-native only.

## SentinelFetal2 nuance
- Evaluate whether legacy Dash dependencies are still baseline runtime.
- Keep torch/scipy/sklearn/fastapi chain coherent for inference + API paths.
- Ensure scripts that users execute in standard setup have their dependencies declared.
