install:
	curl -s https://install.zerotier.com | sudo bash

create-network:
	@if [ ! -f ./.env ]; then \
		echo "No .env file found — creating .env..."; \
		touch ./.env; \
	fi
	@echo "Creating ZeroTier network..."
	@bash create_ztnetwork.sh

add-node:
	@if [ -z "$(NODE_ID)" ]; then \
		echo "Usage: make add-node NODE_ID=<member-id>"; \
		echo ""; \
		echo "Example: make add-node NODE_ID=7654aa1eaa"; \
		exit 1; \
	fi
	@. ./.env; \
	if [ -z "$$ZEROTIER_NETWORK" ]; then \
		echo "Error: ZEROTIER_NETWORK not set in ./.env"; \
		echo "Run 'make create-network' first or set ZEROTIER_NETWORK in ./.env"; \
		exit 1; \
	fi; \
	bash authorize_zt_member.sh $$ZEROTIER_NETWORK $(NODE_ID)

join:
	@if [ ! -f ./.env ]; then \
		echo "No .env file found — creating .env..."; \
		touch ./.env; \
	fi
	@if [ -z "$(NETWORK_ID)" ]; then \
		echo "Usage: make join NETWORK_ID=<network-id>"; \
		echo ""; \
		echo "Example: make join NETWORK_ID=5170efff3f3bf6ba"; \
		exit 1; \
	fi
	@sudo zerotier-cli join $(NETWORK_ID); \
	if grep -q "^ZEROTIER_NETWORK=" ./.env; then \
		if [ "$$(uname)" = "Darwin" ]; then \
			sed -i '' "s/^ZEROTIER_NETWORK=.*/ZEROTIER_NETWORK=$(NETWORK_ID)/" ./.env; \
		else \
			sed -i "s/^ZEROTIER_NETWORK=.*/ZEROTIER_NETWORK=$(NETWORK_ID)/" ./.env; \
		fi; \
	else \
		echo "ZEROTIER_NETWORK=$(NETWORK_ID)" >> ./.env; \
	fi

authorize-approved:
	@bash authorize_approved_members.sh

authorize-approved-retry:
	@bash authorize_approved_members.sh --retry-errors

get-peers:
	@if [ ! -f ./.env ]; then \
		echo "Error: No network configured."; \
		echo "Join a network first with: market network join <network-id>"; \
		echo "Or create one with: market network create"; \
		exit 1; \
	fi
	@. ./.env; \
	if [ -z "$$ZEROTIER_NETWORK" ]; then \
		echo "Error: ZEROTIER_NETWORK not set."; \
		echo "Join a network first with: market network join <network-id>"; \
		echo "Or create one with: market network create"; \
		exit 1; \
	fi; \
	./get_peers.sh $$ZEROTIER_NETWORK
