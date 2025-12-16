install:
	curl -s https://install.zerotier.com | sudo bash

create-network:
	@echo "Creating ZeroTier network..."
	./zerotier/create_ztnetwork.sh

add-node:
	@if [ -z "$(NODE_ID)" ]; then echo "Usage: make add-node NODE_ID=<member-id>"; exit 1; fi
	@. ./zerotier/.env; \
	./zerotier/authorize_zt_member.sh $$ZEROTIER_NETWORK $$NODE_ID

get-peers:
	@. ./zerotier/.env; \
	./zerotier/get_peers.sh $$ZEROTIER_NETWORK
