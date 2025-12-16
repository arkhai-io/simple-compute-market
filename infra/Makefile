install:
	curl -s https://install.zerotier.com | sudo bash

create-network:
	@echo "Creating ZeroTier network..."
	@bash zerotier/create_ztnetwork.sh

add-node:
	@if [ -z "$(NODE_ID)" ]; then \
		echo "Usage: make add-node NODE_ID=<member-id>"; \
		echo ""; \
		echo "Example: make add-node NODE_ID=7654aa1eaa"; \
		exit 1; \
	fi
	@. ./zerotier/.env; \
	if [ -z "$$ZEROTIER_NETWORK" ]; then \
		echo "Error: ZEROTIER_NETWORK not set in ./zerotier/.env"; \
		echo "Run 'make create-network' first or set ZEROTIER_NETWORK in ./zerotier/.env"; \
		exit 1; \
	fi; \
	bash zerotier/authorize_zt_member.sh $$ZEROTIER_NETWORK $(NODE_ID)
	
	```
get-peers:
	@. ./zerotier/.env; \
	./zerotier/get_peers.sh $$ZEROTIER_NETWORK
