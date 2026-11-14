---
tags: [engineering, configuration]
---

# Configuration

How a service reads its own settings and how a deployment supplies them: the layers
a configuration resolves through, where secrets and trust travel, how a setting is
named and retired, and where a stack's configuration lives. The Python form, with
Dynaconf, is [Configuration in Python](configuration-python.md); a cluster's and a
chart's forms are [Kubernetes](kubernetes.md) and [Helm](helm.md). A document
describing resources a service holds is a [definition document](definition-documents.md).

## Profiles layer over committed defaults

A service resolves its configuration from layers, highest priority first:

1. Environment variables under the service's own prefix: a last-resort escape hatch,
   never the normal way to supply configuration.
2. Profile files, one per active profile, applied in the order the profiles are
   listed.
3. A base configuration file in the configuration directory, giving default values.
4. Committed defaults packaged with the service.

Two variables select which configuration loads: the list of profiles to layer and
the directory the profile files are read from. These are the resolver variables.

## Application settings stay out of the environment

Environment variables are the highest-priority override layer. Baking application
settings into an image's build instructions, or setting them as individual variables
of a container, silently overrides anything an operator configures through a profile
file — the opposite of the profile system's purpose. An image or a container sets
only the resolver variables. A variable an external subprocess reads directly from
the process environment, rather than through the service's own settings object,
cannot travel through the configuration loader, so the service reads it from its
resolved settings at startup and writes it into its process environment once,
explicitly, rather than having the container set it. `ANSIBLE_CONFIG`, which the
`ansible-playbook` subprocess reads itself, is such a variable.

## The configuration system carries every value

Every configuration value reaches a service through its configuration system: its
configuration files and its loader's documented override layer. A value travels
outside that system only when it controls which configuration is loaded — the
configuration directory and the profiles to layer. A deployment's definition knows a
configuration value only where the deployment itself needs it for a stated reason,
such as the port its container, probes, and service share, or the path of a file it
mounts, and supplies outside the configuration system only the values that select
which configuration loads.

Conformance is a property of the source and the deployment definitions, judged there,
never a runtime refusal: a service does not refuse to start because a value reached
it through its environment, and the override layer stays available to an operator
correcting a development cluster.

## Secrets travel in a secret profile or overlay file

In every stack, local or deployed, a service takes each secret it needs — an API
key, a bearer token, a wallet key — as a setting in a file its configuration system
layers: a secret profile added to the active profiles, or a secret overlay file. On a
cluster that file is a key of a cluster secret, which the deployment's secret store
writes; under a local container stack it is a mounted file. A setting that names an
environment variable holding the secret is a second, weaker channel beside the one
the deployment already writes, so a service's configuration does not name one.

## Trust is configured where its client reads it

Trust follows the same rule as secrets. A private CA is a configured bundle path that
the one client needing it reads, never `SSL_CERT_FILE` or any other setting that
replaces the whole process's trust store, which would replace its public trust as
well. A client naming no bundle uses the default trust store.

## A private CA is mounted once, and each client names it

A deployment mounts a deployment-supplied CA bundle at one fixed path, and every
client that trusts that CA names the file as its own bundle path; one CA that issues
several services' certificates is one mount, however many clients name it. Where the
deployment renders the setting, it derives the path from the mount rather than taking
it as a value beside the mount, so the two cannot disagree ([Helm](helm.md) gives a
chart's form). Where the setting lives in a secret overlay the deployment never
renders, the deployment cannot derive it: whoever writes that secret states the
deployment's mount path, and a check running the client's access check from the
deployed service's own mounts proves the two agree. A client loads its bundle when it
is built, so a bundle that cannot be loaded fails the access check at its
configuration step, before any request.

## A setting that belongs to one domain is named for it

A setting that belongs to one domain is named for that domain, with no alias: a
service running two kinds of job reads `batch_script_path` and `stream_script_path`,
never one `script_path` serving both. A renamed setting is refused rather than
ignored, because an ignored key would silently fall back to a default the operator
meant to replace: the service's first startup step refuses a configuration stating
the retired name in any layer, environment included, naming its replacement. A
setting retired because the service stopped needing it is not refused, since ignoring
it changes nothing the service does.

## A stack's configuration lives in committed files

Every stack a repository runs — a development stack, an end-to-end lane — takes every
value it runs with from committed profile, overlay, values, and secret-overlay files,
whose secret overlays hold public development values only. A deployed stack's secret
profile or overlay is never a committed file: it is the file an operator-supplied
secret holds. The build tooling that starts a stack chooses which configuration loads
— the stack files, a profile, a mode — and never generates or carries a value itself.
A value the base topology fixes stays in the base file; a deployment's own bindings
and values are in its overlay. A base file binds no identity, configuration file, or
secret, and gives none of them — no credential, no definition document — a committed
fallback.
