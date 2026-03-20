deploy: deploy-buyer-agent

# Todo, figure out what this volume was doing in the compose file: #      - zerotier-buy:/var/lib/zerotier-one
deploy-buyer-agent:
	docker run --rm -d --network market --name market-agent-buy -p 8000:8000 \
	--cap-add NET_ADMIN --cap-add SYS_MODULE --device /dev/net/tun:/dev/net/tun \
	--env-file ./agent/.env.alice.docker-compose --env-file ../shared-env/.env \
	arkhai:core

deploy-seller-agent:
	docker run --rm -d --network market --name market-agent-sell -p 8001:8001 \
	--cap-add NET_ADMIN --cap-add SYS_MODULE --device /dev/net/tun:/dev/net/tun \
	--env-file ./agent/.env.bob.docker-compose --env-file ../shared-env/.env \
	arkhai:core