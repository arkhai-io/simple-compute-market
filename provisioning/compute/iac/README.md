# Compute provisioning IaC

The shared roles own buyer relay installation and proxy edits for compute hosts.
Run `make test` for structural checks and local-file, shell, HTTP, and native
Ansible behavior tests. Native tests skip when supported Ansible or its JSON
callback is missing; `make native-ansible-gate` fails on a skip. Set `PYTHON` to
the Python environment containing PyYAML when invoking the native gate directly.
The root `make test-provisioning-iac-native` runs it in the provisioning image.

`frp-binary` takes `frp_binary_name` (`frpc` or `frps`) and returns
`frp_binary_path`. Version 0.61.1 and linux_amd64 are the defaults. An operator
can override `frp_platform` and the `frp_archives` mapping for another verified
platform. Every entry needs a version-specific release URL and pinned SHA-256.

`relay-client` requires `frp_server_addr` and `frp_auth_token`. It maintains
`/etc/frp/frpc-buyers.toml` without discarding proxy blocks, retains a generated
per-host admin password, and runs `frpc-buyers`. The admin port defaults to 740;
it must also fall below the host's effective unprivileged-port boundary.
A changed connection baseline or versioned unit restarts the client, so perform
baseline changes after draining its leases. Proxy diffs reload it.

`relay-proxy` takes `relay_proxy_action` (`add` or `remove`) and a full
`relay_proxy_name`. An add also takes `relay_proxy_local_ip`,
`relay_proxy_local_port` (default 22), `relay_proxy_remote_port`, `relay_grant`,
and the relay-client inputs. Names contain only letters, numbers, dots, dashes,
and underscores, starting with a letter or number. Provider extra variables cannot set the proxy action, identity, local or remote
targets, or runtime client and helper controls. The family reserves these names
at preparation and execution, including jobs with no relay. `relay_client_config`
is host configuration: configure it through operator inventory or host
preparation, rather than a pool's provider extras. Unrelated provider options
remain allowed. Raw operator Ansible `-e` remains Ansible's own authority.

Every proxy uses exact
`# BEGIN/END ANSIBLE MANAGED RELAY PROXY <name>` markers.

Every add and remove attempt installs the root-owned, owner-only helper
`/usr/local/lib/arkhai-relay/remove_proxy.sh` in a root-owned directory and
returns its path as `relay_proxy_teardown_library`. A generated cleanup script
sources this file under `set -e` and calls
`remove_guest_proxy <config> <full-proxy-name> <loopback-reload-url>`.
A missing or unreadable configuration fails removal: a running client may still
hold its proxies. Valid configuration with neither marker nor pending record is
idempotent absence. The helper reads the admin password from the root-only config, supplies it to
curl through stdin, and never restarts the client. It sets `GUEST_PROXY` to
`absent` or `removed` on success. A failed reload returns failure and retains
`<config>.reload-pending.<name>`; the next call retries the reload even though
the block is gone. Missing helpers and failed removals must fail cleanup.

`relay-server` requires the operator's `frp_auth_token`; `frp_proxy_ports` is
the common list of ranges for frps, ufw, and fail2ban. The role prepares native
systemd frps. Admission must be installed and verified before serving buyers.
Host and relay deployment, real frp traffic, and tenant isolation are separate
validation from these local tests.
