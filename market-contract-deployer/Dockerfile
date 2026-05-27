FROM python:3.13-alpine

RUN apk add --no-cache curl

WORKDIR /app

# deploy_alkahest.py is stdlib-only and replays the committed transactions
# file; no other dependencies needed.
COPY deploy-local.sh deploy_alkahest.py alkahest-transactions.json ./
RUN chmod +x deploy-local.sh

ENV RPC_URL=http://anvil:8545
ENV CHAIN_ID=31337

CMD ["sh", "-c", "./deploy-local.sh"]
