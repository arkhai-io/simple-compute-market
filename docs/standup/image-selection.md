# Deployable Image Selection

This document defines the canonical way to select the exact deployable images
for the production stand-up path.

## Inputs

- the intended repo revision for the deployment
- Docker and access to the target Artifact Registry
- permission to run or inspect the publish workflows for that revision

Record the intended repo revision before publishing or selecting images:

```bash
git rev-parse HEAD
```

## Output Manifest

Write the chosen immutable images to a host-local manifest at
`/etc/simple-market-service/image-manifest.env`:

```bash
sudo install -d -m 0755 /etc/simple-market-service
sudo tee /etc/simple-market-service/image-manifest.env >/dev/null <<'EOF'
REGISTRY_IMAGE=us-east4-docker.pkg.dev/<gcp-project>/erc-8004-registry/erc-8004-registry-py@sha256:<digest>
PROVISIONING_IMAGE=us-east4-docker.pkg.dev/<gcp-project>/async-provisioning-service/async-provisioning-service@sha256:<digest>
SELLER_AGENT_IMAGE=us-east4-docker.pkg.dev/<gcp-project>/a2a-agent/a2a-agent@sha256:<digest>
BUYER_AGENT_IMAGE=us-east4-docker.pkg.dev/<gcp-project>/a2a-agent/a2a-agent@sha256:<digest>
EOF
```

Use immutable digests such as `@sha256:<digest>`, not floating tags like
`latest`. Seller and buyer can point at the same agent digest, but keep both
keys so the deployment artifact is explicit.

## Publish Paths

The repo's default publish workflows are:

- `.github/workflows/docker-build-push-erc8004-registry.yml`
- `.github/workflows/docker-build-push-async-provisioning.yml`
- `.github/workflows/docker-build-push-core-agent.yml`

Use one of these patterns:

1. Run the publish workflow for the intended revision, then copy the resulting
   image digests into `/etc/simple-market-service/image-manifest.env`.
2. Build and push the images yourself from the intended revision, then record
   the pushed digests in `/etc/simple-market-service/image-manifest.env`.

Do not continue to service deployment until every image in the manifest is tied
to the intended revision and registry location.

## Verification

Before using the service-specific stand-up runbooks, source and verify the
manifest:

```bash
set -a
. /etc/simple-market-service/image-manifest.env
set +a

sudo docker pull "${REGISTRY_IMAGE}"
sudo docker pull "${PROVISIONING_IMAGE}"
sudo docker pull "${SELLER_AGENT_IMAGE}"
sudo docker pull "${BUYER_AGENT_IMAGE}"
```

If any pull fails, fix the publish/auth step before moving to the service
runbooks.
