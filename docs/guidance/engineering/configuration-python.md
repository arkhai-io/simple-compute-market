---
tags: [engineering, configuration, python]
---

# Configuration in Python

The Dynaconf form of [Configuration](configuration.md)'s profile resolution: the
files each layer is, the options the loader is built with, and where a dotenv file's
values land.

## The layers in Dynaconf

A committed `settings.toml` supplies the base defaults; a `config.yml` in the
configuration directory gives default values; one `config-<profile>.yml` per active
profile layers overrides on top, applied in the order the profiles are listed; and
environment variables under the service's `envvar_prefix` are the highest-priority
override, the escape hatch. Each service picks its own `envvar_prefix` — a payments
service `PAYMENTS`, say — and builds Dynaconf with `environments=False`, using named
profiles instead of Dynaconf's built-in environment concept, layered through
`includes=[...]` with `merge_enabled=True`.

## Dotenv values join the environment layer

Dynaconf's dotenv loading contributes prefixed variables to the environment layer
rather than creating a file layer below the profile includes. An already-set process
variable wins over the same dotenv key; otherwise a dotenv-sourced prefixed variable
overrides settings, secrets, base configuration, and profiles just like any other
environment value.
