#!/usr/bin/env bash
# Usage: ./set-ssh-passphrase.sh /path/to/private/key
# If no argument is given, defaults to ~/.ssh/id_rsa

KEY_PATH="${1:-$HOME/.ssh/id_rsa}"

if [ ! -f "$KEY_PATH" ]; then
  echo "Error: key file not found at '$KEY_PATH'" >&2
  exit 1
fi

# Start ssh-agent and export its environment
eval "$(ssh-agent -s)"

# Add the specified key
ssh-add "$KEY_PATH"