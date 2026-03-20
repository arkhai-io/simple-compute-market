ARG CONTRACTS_IMAGE=arkhai:contracts-latest

FROM ${CONTRACTS_IMAGE}

WORKDIR /app

COPY deploy-local.sh .

#Todo: Compile contracts in advance so that they aren't compiled at runtime.