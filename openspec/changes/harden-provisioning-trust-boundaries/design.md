# Design: harden the provisioning service's trust in hosts and guests

## Context

The proposal groups Goal 1's trust gaps by theme (its D1). Reading the code against
it corrected several of its claims, and the decisions below rest on the corrected
account.

**One Ansible configuration, which an operator's replaces whole.** The service
exports the packaged `compute_provisioning_ansible/ansible.cfg` as `ANSIBLE_CONFIG`
(`provisioning/compute/service/src/compute_provisioning_service/app_runtime.py`),
or the file the profile's `ansible_cfg` names, which replaces the packaged one whole.
`domains/vms/provisioning/iac/ansible/ansible.cfg` serves operators running the
domain's playbooks by hand and the syntax gates. Ansible's ssh plugin emits
`StrictHostKeyChecking=no` ahead of any common arguments when checking is off, and
`ssh` keeps the first value it reads for each option, so verification set only in a
configuration file is undone by an operator's own file. The inventory a job runs
against is written by `AnsibleRunner.write_inventory`
(`provisioning/compute/ansible/src/compute_provisioning_ansible/runner.py`); no host
key is recorded anywhere, and no `known_hosts` is mounted.

**What impersonating a host yields.** Public-key authentication sends no private key
and binds its signature to the session, so an impersonator does not obtain the
deployment's SSH key. It receives what a playbook sends the host: the relay's client
token, which every host on that relay shares, and the host's frpc admin password
(the `relay-client` role), a buyer's `authorized_keys` and tenant password; and the
service records success. A host behind a management tunnel is reached at
`ssh_host:ssh_port` like any other, several hosts may share one `ssh_host` on
different ports, and nothing reserves a management port to one host.

**Guests share more than a segment.** Every guest, with or without a GPU, attaches to
libvirt's `default` network (`virbr0`, `192.168.122.0/24`) from nine `virt-install`
sites in the `vm-management` role, takes its address by DHCP, and has it pinned as an
`ip-dhcp-host` reservation in `default`. The host kit filters guest traffic only on
the host's port 22 (`vm-setup/tasks/security-hardening.yml`): guests reach each other
at layer 2 and layer 3, every other host port, the seller's private networks through
the shared masquerade, and, on a host that is itself a cloud VM, the provider's
metadata service. libvirt accepts forwarding from `virbr0` back to `virbr0`, and on a
shared segment one guest can claim another's address by ARP and receive the DNATed
buyer connections meant for it. The VM IaC README claims "complete tenant isolation
with separate network ranges" and shows a `tenant_isolation.network` block no task
applies, and the host kit prints that isolation rules are configured. Guest isolation
is `physical-provisioning`'s, which holds the VM role's requirements, not
`resource-pool-management`'s.

**The host credential.** Only `POST` and `PUT /api/v1/hosts` with `secrets` carry key
material over the wire; the INI import's `embedded` mode reads each key file from the
service's own filesystem (`inventory.py`). `fernet-v1` is bare Fernet under
`ssh_decryption_key` (`kit/config/src/market_config/secret_at_rest.py`), with no key
id and no binding to its host, and the same key protects relay admission tokens and
grant-signing keys. This change defers the credential (D11).

**The administrator stances are deliberate.** The provisioning service refuses at
table assembly a route that does not admit `admin`, and `kit/site` admits `admin` on
every site contract through `permits()`, with its reason in
`kit/site/src/market_site/auth.py` and a test. The VM, bare-metal and API-credits
storefronts admit the administrator only on administrator routes; their buyer,
counterparty-seller and service routes refuse it, and an administrator acts on a
negotiation only through advance and force-accept, which record `sender_role=admin`.
Bare-metal lease-ready evidence admits buyer, seller and admin as readers. The
registry's administrator is the bearer key `REGISTRY_ADMIN_API_KEY`. The API-credits
storefront serves `GET /api/v1/listings/{id}/negotiations` and
`…/negotiations/{neg_id}` unauthenticated, though the shared storefront client
already signs both as administrator operations. `redesign-authenticated-requests`
does not touch route roles.

**What has been deployed.** The newest release tag this design read is
`marketplace-v0.3.0` (`git log --tags --no-walk --decorate`; the remote was not
fetched). It shipped `ssh` connection version 2, `fernet-v1` host keys under the
shared key, host-key checking off, and guests on the shared segment. The provisioning
migration chain receives only the database connection
(`provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`),
so no migration can learn a host's key or re-protect a value.

**What the real-host proof can reach.** The e2e harness reaches the provisioning
service through its typed clients and a delivered guest through the shared SSH
helper, as the guest's buyer; the guest's tenant user has sudo through the `sudo`
group with a generated password, which the deal delivers to the buyer in settle
status's tenant credentials (`vm-management/tasks/vm-create.yml`; the VM storefront's
`fulfillment_result_connection`). Nothing offered to a test restarts a host
service, reloads its firewall, or runs host preparation: the VM operator client runs
fixed playbooks, and host preparation is run by an operator. The bare-metal
qualification already reaches its host through a harness-local operator route its
target names (`cleanup_qualification.operator`), running fixed observer code under
`sudo -n` over the shared SSH seam (`working_data_qualification.py`), and
`test-compatibility` admits such independent operator observations.
`e2e_vm_real_provisioning` already holds two deal guests on one host at once, with a
heartbeat held on the first (its stages `09f`–`09n`).

## Goals / Non-Goals

**Goals:**

- The provisioning service checks every host the Ansible executor reaches against a
  pinned host key, and sends nothing to a host it has not checked, except the probes
  that pin a key.
- A VM guest reaches no other guest on its host, no service on its host but DHCP and
  DNS, and no link-local or private destination unless the seller lists it.
- The administrator's reach is one rule for every service, recorded and held by each.
- Every compatibility path this change adds carries a stated retirement, and the
  repository records retirements where releases are decided.

**Non-Goals:**

- Host credential protection (D11), relay secrets under `ssh_decryption_key`, and
  migrating `fernet-v1` values.
- Shared-relay admission, emergency rotation, and the admission plugin's pin
  (`harden-shared-relays`).
- Isolating bare-metal tenants, who hold a whole machine.
- The host's own SSH into a guest it just created, a hop local to the host.
- How the registry's administrator authenticates, and the API-credits service's
  `X-Admin-Key` fallback (`redesign-authenticated-requests`).
- Listing the compatibility paths already in the code.

## Decisions

### D1 — One change for the provisioning trust gaps

Decided by the owner before design: Goal 1's unowned trust gaps are grouped by theme
into this change. D2 and D11 settle which of them it keeps.

### D2 — The change keeps host keys, guest isolation and the administrator stance together

The change keeps host-key verification, guest isolation and the administrator stance,
reviewed against one threat model: what the provisioning boundary trusts. The
credential leaves it (D11).

Rejected: splitting out the administrator stance alone, or it and guest isolation, so
that each change has one acceptance boundary and one kind of evidence. The cost of
keeping them together is that closeout waits on guest isolation's proof on a real
host; the owner chose one review of the boundary over that cost.

### D3 — A host's key is stated, or captured by an operator's probe

A key the operator states at registration is the host's pin. A host registered
without one has no pin, and the Ansible executor refuses every job against it before
anything runs. An operator's connectivity check of an unpinned host reports the key it
presents, and the capture route (D5) records it; no job pins a key, except the
adoption of a host deployed before pins existed (D6).

The capture is a probe that sends nothing secret: `ansible -m ping` ships a module and
no credential. A host's first contact is otherwise usually its preparation job, which
sends the relay token; capturing there would hand that token to whoever answered.

Rejected:
- capture on first contact alone (trust on first use), which makes that preparation
  job the unchecked contact;
- capture on any first contact beside stated keys, for the same reason;
- stated keys alone, which breaks every registration, document and lane helper and
  strands every deployed host until it is given a key;
- an SSH host certificate authority, which needs a CA run by the operator and leaves
  a host prepared by another party unsigned; the representation leaves room for it.

### D4 — The pin is `host_keys` in the `ssh` connection, at version 3

The `ssh` connection gains `host_keys`: a list of OpenSSH public keys, each its type
and base64 without a comment, which the codec parses and refuses when empty. The
connection is served at version 3 alone, since version 2 shipped. A submission that
omits `host_keys` keeps the stored pin, as one that omits a protected key keeps it; a
change of `ssh_host` or `ssh_port` keeps it too, since the key identifies the machine,
not its route. The host definitions document and its export carry `host_keys`; the
INI import carries none and keeps the stored pin. The migration chain rewrites every
version-2 connection to version 3 with the same public fields and protected values and
no `host_keys`, an exact mapping, and marks each host it rewrites (D6).

```yaml
hosts:
  - host_id: kvm1
    pool_id: vm-default
    connection:
      kind: ssh
      version: 3
      public:
        ssh_host: 10.0.0.5
        public_host: 203.0.113.9
        ssh_user: ubuntu
        key_path: /home/appuser/.ssh/id_ed25519
        host_keys:
          - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIK0p…
```

For each job and probe the runner writes an owner-only `known_hosts` beside any
decrypted key file, removed with it, keyed `[ssh_host]:ssh_port`, and renders
verification as host variables, which outrank any configuration:
`ansible_host_key_checking=true`, `ansible_ssh_args` with the service's own baseline,
and `ansible_ssh_common_args` naming the file with `GlobalKnownHostsFile=/dev/null` and
`StrictHostKeyChecking=yes`. A host behind a management tunnel is checked at its
tunnel port, and a port handed to another machine is refused on mismatch.

The rule belongs to the Ansible executor, whose concept the host key is: the mock
executor ignores pins, as protected keys are checked only once an Ansible executor is
real, and every lane registers hosts without keys.

Rejected:
- a host-key record beside the connection, which puts an SSH concept in the host
  authority against the requirement that a codec owns its kind's fields, or needs a
  new part of the envelope for every kind;
- a `known_hosts` file the operator mounts, which splits the connection's descriptor
  into configuration, cannot receive a capture, and makes the inventory
  unreproducible from the registry;
- a host variable per key type in the INI, which the parser's split on spaces would
  need changed for an import route no client in this repository calls.

### D5 — The check reports, the capture route records, and a mismatch is refused before the start

**Capture.** On an unpinned host, the connectivity check connects with `accept-new`
into a file it discards, stores nothing, and reports the key presented; on a pinned
host it reports whether the key matched. The connectivity result gains `host_key`:

```json
{"host": "kvm1", "reachable": true, "detail": "kvm1 | SUCCESS …",
 "host_key": {"endpoint": "[10.0.0.5]:22", "pinned": false,
              "presented": "ssh-ed25519 SHA256:Q1m9xkP3…"}}
```

`host_key` is null when no key was presented — the probe timed out, was refused, or
reached no SSH handshake — with `reachable: false` and the probe's reason in `detail`;
it is omitted only for a connection kind whose hosts present no key.

`POST /api/v1/hosts/{host}/host-keys/capture`, with the fingerprint the operator
compared, probes the host again and records the key only when it presents that
fingerprint. It answers, as the connectivity check answers an unknown host and a kind
with no probe:

- 404 for an unknown host;
- 422 for a host whose connection kind presents no key, naming the kind, and for an
  empty or malformed fingerprint (not `SHA256:` and base64), naming the field;
- 409 with a code for each refusal, recording nothing: `host_key_mismatch`, with the
  endpoint and the presented fingerprint; `host_key_pinned`, with the pinned
  fingerprints, for a pinned host unless the body says `"replace": true`; and
  `no_host_key_presented`, with the endpoint and the probe's reason, when the probe
  reaches no handshake;
- on success, the endpoint and the pinned fingerprints.

The route is the administrator's (D14), and the family client offers it as
`capture_host_key(host_id, fingerprint, *, replace=False)`, surfacing each refusal's
code so a caller branches on it rather than on text (17 F5).

**Rotation.** Keys are replaced by stating new ones or capturing with `replace`;
stating the old key with the new lets a host rotate without a refusal between.

**Refusal.** Before recording a job's `execution_started_at`, the Ansible executor
makes one SSH connection against the pin that runs nothing on the host. A mismatch, or
an unpinned host, fails the job as never started, so a teardown refused this way runs
again once the operator settles the key; a key that changes between that check and the
playbook fails the playbook as started, and an operator handles it. A host-key refusal
is not retried. Its message names the host, `[ssh_host]:ssh_port`, the presented and
pinned fingerprints, and how to recover, in the job's error, the connectivity result,
and readiness.

Rejected: a `GET` connectivity check that stores the key, a read that writes and pins
what nobody compared; a capture route taking no fingerprint; refusing inside the
playbook, which counts the job as started and holds a teardown for an operator though
nothing touched the host; a separate rotation operation with its own result type,
which duplicates what stating keys or capturing with `replace` already does (17 F5).

**The real-target harness (26 F1).** The real VM scenarios pin a host only from an
independent source: the target's stated `ssh_host_public_key`, or a pin already
stored, an earlier run's or one an operator captured after comparing the presented
fingerprint. With neither, a scenario refuses before declaring capacity, naming the
field; it never captures the key a host presents, since comparing an observation with
itself is trust on first use, and its jobs then send the relay token and a buyer's
keys to whatever answered. The target's key stays optional, so a profile for a host
already pinned keeps working. Rejected for the harness: requiring the key in every VM
target, which fails a profile for an already pinned host until the key is added; an
expected fingerprint in the target passed to the capture, a further target field for
a capture section 4's local SSH fixture already exercises; observing and capturing,
as first implemented.

### D6 — Hosts deployed before pins are adopted by the probe before their first job

The migration of D4 marks each host it rewrites as pending adoption, a flag on the
`hosts` row outside the connection, which neither the export nor the document carries.
For a pending host, the check before a job's start, or the connectivity check, connects
with `accept-new` into an empty file and records the key presented as the host's pin,
clearing the mark, in one compare-and-set: the write takes effect only while the host
is still pending. Whichever adoption wins, every job then re-reads the committed pin
and makes the ordinary check before its start against it, as for a host always pinned;
its playbook's `known_hosts` is rendered from that committed pin, never from the key
the job observed. A job whose observed key lost to another fails that check, before its
start is recorded. Stating `host_keys`, or capturing, clears the mark as well; a
capture arriving after an adoption committed meets a pinned host and answers
`host_key_pinned` unless it states `replace`, and a submission stating `host_keys`
replaces the adopted pin, as the operator's explicit word. A host registered after the
upgrade is never marked (17 F1). Readiness lists pending hosts, as information rather than a reason for being
not ready, once an Ansible executor is real.

The adopting connection runs nothing and sends nothing secret, so no secret reaches an
unchecked host; what it trusts is a deployed host's first answer after the upgrade,
which is what those hosts have been trusted with on every contact since they were
registered.

The adoption retires at 0.3.3, or at the second release after the one first carrying
it, whichever is later: the flag, the `accept-new` path of both checks, and readiness's
list of pending hosts are removed, and a host still pending is then plainly unpinned
and refused until an operator captures or states its key. Its row is in the release
handbook's "Compatibility to retire" (D16); the migration that writes the flag retires
when a migration floor absorbs it.

Rejected:
- strict refusal of every deployed host until an operator pins it, an outage from the
  upgrade until each host is pinned, racing the lease watchdog's 3600 seconds;
- a bounded capture on a deployed host's first job, whose contact may carry the relay
  token, and which races two first jobs;
- a per-host lock held until the pin is committed and every waiting job has verified,
  which holds one service process's lock across an SSH handshake (17 F1);
- two releases, accepting pins then enforcing them, which needs an enforcement switch
  for one release and ordered releases;
- an enforcement setting, a security control a configuration turns off.

### D7 — Guests are isolated by bridge port isolation, an anti-spoofing filter, and a forwarding drop

Every guest's interface is defined once for all nine `virt-install` sites:

```xml
<interface type='network'>
  <source network='default'/>
  <model type='virtio'/>
  <port isolated='yes'/>
  <filterref filter='clean-traffic'>
    <parameter name='CTRL_IP_LEARNING' value='dhcp'/>
    <parameter name='DHCPSERVER' value='192.168.122.1'/>
  </filterref>
</interface>
```

Every site takes these arguments from one template the role looks up
(`vm-management/templates/guest-interface-args.j2`): `--network
network=default,model=virtio` and `--xml` edits adding the port and the filter. It is
a template rather than a variable because a pool's `extra_vars` override any variable,
so a pool could otherwise put guests back on a shared segment.

An isolated bridge port forwards only to ports that are not isolated, here `virbr0`
itself, so guests reach DHCP, DNS and the NAT uplink but never each other at layer 2.
`clean-traffic` holds each guest to its MAC address and the address it leased, which
closes the ARP takeover. The host kit adds, first in its own forwarding chain and
installed by its own unit (D8),
`-i virbr0 -o virbr0 -m comment --comment arkhai-guest-isolation -j DROP`,
closing the hairpin through the gateway. `default`, the DHCP reservations, address
discovery, and every teardown path are unchanged. A GPU guest needs nothing different.
Host preparation refuses, naming each missing item, a host with libvirt older than
6.1, without the nwfilter driver's `clean-traffic` filter, with virt-install older than
3.0 — whose `--xml` is the only way to set the filter's parameters — or without
`ebtables`, which host preparation installs. The VM IaC README's and the host kit's
false isolation claims are corrected.

The real-host proof is D22's observations O1 and O2. Static role tests hold the
interface definition and the rule.

Rejected:
- nwfilter rules alone, a filter of our own kept correct by hand with ARP and
  broadcast handled for DHCP;
- a libvirt network per guest, which needs subnet allocation, a dnsmasq per guest, a
  rewrite of every teardown and lookup path reading `default`, and two teardown shapes
  while old guests run;
- private VLANs, which need a switch or its emulation for traffic that never leaves
  the host.

### D8 — A guest reaches DHCP and DNS on its host and no private destination unless listed

The host kit installs the guest policy, D7's hairpin drop with it, in two chains of its
own, each jumped from the first position of its built-in chain:

```text
-I INPUT 1 -i virbr0 -j ARKHAI-GUEST-IN
-A ARKHAI-GUEST-IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A ARKHAI-GUEST-IN -p udp --dport 67 -j ACCEPT
-A ARKHAI-GUEST-IN -d 192.168.122.1 -p udp --dport 53 -j ACCEPT
-A ARKHAI-GUEST-IN -d 192.168.122.1 -p tcp --dport 53 -j ACCEPT
-A ARKHAI-GUEST-IN -m comment --comment arkhai-guest-isolation -j DROP

-I FORWARD 1 -i virbr0 -j ARKHAI-GUEST-FWD
-A ARKHAI-GUEST-FWD -o virbr0 -m comment --comment arkhai-guest-isolation -j DROP
-A ARKHAI-GUEST-FWD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A ARKHAI-GUEST-FWD -d <each guest_allowed_private_destinations entry> -j ACCEPT
-A ARKHAI-GUEST-FWD -d 169.254.0.0/16 -j DROP
-A ARKHAI-GUEST-FWD -d 10.0.0.0/8 -j DROP
-A ARKHAI-GUEST-FWD -d 172.16.0.0/12 -j DROP
-A ARKHAI-GUEST-FWD -d 192.168.0.0/16 -j DROP
-A ARKHAI-GUEST-FWD -d 100.64.0.0/10 -j DROP
```

`guest_allowed_private_destinations` is empty by default. The forwarded
established/related accept carries a guest's replies to a buyer who connected from a
private address, on the seller's LAN, a network the host sits in, or a shared carrier
NAT; a connection the guest itself opens toward a private address has its first packet
dropped and never becomes established (17 F3).

The chains are reached before anything UFW or libvirt installs: an appended rule would
follow UFW's accepts on INPUT and libvirt's `LIBVIRT_FWO` accept on FORWARD and never
run, and under libvirt's nftables backend its accepts sit in a table of their own,
where they stop no drop in the filter table. The host kit removes its own
`ufw allow in on virbr0 from 192.168.122.0/24`, which accepts every packet from a guest
to the host, and the scattered port-22 rules, which collapse into the default deny; its
`allow out on virbr0` governs only the host's own connections to guests and stays;
removing the older rules from a host an earlier release prepared is a compatibility
path (D23). The chains and both jumps are installed in one `iptables-restore -w
--noflush` transaction that fills the chains and puts each jump first, run by
`arkhai-guest-policy.service`, a oneshot started at boot and with every libvirtd start,
and by `/etc/ufw/after.init` on UFW's start, so both jumps are first again after
libvirt restarts and after UFW reloads (17 F4). The policy does not rely on the host
kit's `iptables-restore` unit, which restores nothing at boot on a host with neither
`/etc/iptables` nor `/etc/sysconfig`, an unowned gap in the change index. cloud-init
reads a seed ISO, and the host's SSH into a guest, frpc's proxy, and DNATed buyer SSH
are connections the host opened or forwards, so none needs more.

A VM create inserts its guest's two forwarding accepts for DNATed buyer SSH at
`FORWARD`'s first position, ahead of the policy's jump. They match no packet a guest
originates: the inbound accept requires `! -i virbr0`, and the reply accept
`--ctstate ESTABLISHED`, so neither admits another guest's connection through the
gateway nor a connection a guest opens.

A guest that reaches the seller's network, its management route, or its cloud
credentials has crossed the boundary a seller places beside buyers as surely as one
that reaches another guest.

The real-host proof is D22's observations O3 to O7.

Rejected: host services alone, leaving the seller's network and cloud metadata open;
host services and link-local alone; nothing beyond D7; installing the policy through
UFW's `before.rules`, which couples it to UFW's layout and leaves hosts without UFW
needing another path (17 F4); limiting buyers to public addresses, which narrows the
topologies delivered to (17 F3).

### D9 — The host kit converges running guests live

For each running guest, the host kit sets the bridge flag on its tap
(`bridge link set dev <tap> isolated on`), which does not drop the link, applies
`clean-traffic` through `virsh update-device --live` where libvirt accepts it and
otherwise at the guest's next start, and writes both into the guest's saved definition
so a host reboot or autostart keeps them. No buyer connection is interrupted. The host
kit reports any guest it could not converge. The convergence is one installed command
(D20), and its real-host proof is D22's observations O8 and O9. An isolated port can still be reached
from one that is not, so without this a guest created before the change could reach new
guests at layer 2 for as long as it runs, and VM leases may be open-ended.

The convergence retires at the same release as D6's adoption, with its row in
"Compatibility to retire"; the operator handbook's upgrade procedure has the operator
run the host kit on every VM host before then, and a guest never converged keeps a
port that is not isolated until it is torn down.

Until such a guest's filter applies, port isolation keeps it from other guests at
layer 2, but not from claiming another guest's address to the host's own end of the
bridge. The owner reaffirmed this decision against that exposure (17 F2).

Rejected: isolating new guests only, which leaves new guests' isolation to the oldest
guest on the host; restarting running guests, which interrupts every buyer; failing
host preparation for a guest that cannot take the filter live, leaving its restart to
the operator, and a permanent neighbour entry for its leased address as a host-side
substitute (17 F2).

### D10 — No guest shares a segment with another by anyone's choice

No pool or seller setting places guests on a shared segment: a seller gains nothing by
it, and different buyers' guests sharing one is the exposure this change removes. A
private network for one buyer's guests is a buyer feature, needing a representation in
negotiation and on the claim; it is an open question.

Rejected: a pool setting such as `guest_network: shared`.

### D11 — Host credential protection is deferred to an unowned gap

Host credential protection leaves the change as an unowned gap in the change index;
the roadmap's row names it unowned. Nothing else here depends on it: host keys change
the connection's public fields, and a later scheme is a new protected-value scheme and
its codec, with a submission field that needs no further connection version. The
decisions it carried — D12, whether relay tokens and grant keys under
`ssh_decryption_key` move too, and D13, how stored `fernet-v1` values migrate and what
readiness reports meanwhile — leave with it. Deferring leaves the transport and the
storage as they are.

The design weighed, and left to that work: sealed submission to a keyring of HPKE keys
with key ids and binding to the host, the scheme it recommended; a reference to a
secret authority, close to `key_path` at a mounted Secret; envelope encryption under a
cloud KMS; and authenticated encryption with key ids.

### D12 and D13 — Deferred with D11

See D11.

### D14 — The administrator reaches every route acting on its operator's resources, and is never a party

The administrator is the operator of the service it calls. It is admitted on every
route that acts on resources that operator owns: every route of the provisioning
service and of a site authority, whose hosts, leases, capacity and ledger are all the
operator's. It is never authorized as a party — a buyer, a counterparty seller, a
service peer — on a route whose authorization binds the caller to a deal; there it acts
only through administrator operations, which record it as the administrator, so a
party's history holds only what that party sent. A storefront's own records of its
deals are its operator's, and its administrator reads them.

Provisioning, the site authorities, and the VM and bare-metal storefronts conform
today; the API-credits storefront's unauthenticated negotiation reads do not (D15).
The provisioning service's seller routes are read as the operator's own resources,
since one business runs sites and storefronts.

Rejected:
- the administrator on every route everywhere, which authorizes it as a negotiation's
  party and breaks principal-bound history;
- the administrator only on administrator routes everywhere, which builds, in the
  authorities, the gate `kit/site` argues against;
- recording the current state with no rule, which leaves the roadmap's gap open.

### D15 — The rule is written once, stated by each service, and held by tests

- **Written.** `ARCHITECTURE.md` gains "The administrator's reach" under "Shared
  vocabulary and identities", after "Authenticated service boundaries".
  `physical-provisioning`'s "Every provisioning route admits the administrator" is
  restated as the rule applied to an authority whose resources are all the operator's,
  its behaviour unchanged; `site-capacity` and `api-credits` gain requirements that
  their site authorities admit the administrator on every route; `storefront-publication`
  gains the requirement that a storefront never authorizes its administrator as a
  party.
- **Held.** Provisioning's assembly refusal and `kit/site`'s test stay. Each storefront
  — VM, bare metal, API credits — gains a test that a request signed as the
  administrator is refused on its buyer, counterparty-seller and service routes and
  admitted on its administrator routes.
- **Fixed.** The API-credits storefront's `GET /api/v1/listings/{id}/negotiations` and
  `…/negotiations/{neg_id}` require the administrator, as the other storefronts' do;
  the shared storefront client already signs them so.
- **Recorded.** The registry's administrator authenticating by a bearer key rather than
  a signed principal is an unowned gap in the change index. The API-credits service's
  `X-Admin-Key` fallback is `redesign-authenticated-requests`'.

Rejected: route-role tables in the storefronts, a rework of three storefronts'
authentication that overlaps `redesign-authenticated-requests`' operation-bound
envelope; the architecture document alone, which leaves three stances in code only;
moving the registry to a signed administrator here.

### D16 — Compatibility code is added with its retirement, recorded where releases are decided

Code that exists only for older deployments is added with a stated retirement and
removed when it falls due. The engineering guidance gains
`retiring-compatibility.md`, a new file beside `versioning.md`, linked from it;
this repository's form is a section of `package-versions.md`; and the release handbook
gains "Compatibility to retire", a table read before a release candidate is loaded and
when a release is cut, with this change's three rows (D6, D9, D23). Their full text, as the
owner accepted it, is in "Promotion text" below. Listing the compatibility paths
already in the code is an unowned gap in the change index.

Rejected: a deferred change per path, the full cost of a change for what is often a
deletion; markers in code with a check, which describe a plan in a comment; rows in the
roadmap or the change index, against their purposes; one statement in `versioning.md`,
too thin for the subject.

### D17 — Two rounds of two sessions, then closeout

The cadence first settled; D24 settles the work remaining after guest isolation's
proof returned the change to design. See "Implementation cadence".

### D18 — The real-host proof reaches the host through an operator route its target names

`e2e_vm_guest_isolation` performs its host-side steps — restarting libvirtd, reloading
UFW, reading the policy's chains and counters, planting a guest to converge, and
running the convergence (D20) — through a harness-local operator route named in the VM
target's opt-in `guest_isolation` section (D21), as the bare-metal qualification's
`cleanup_qualification.operator` is. The route's key is referenced, never copied. The
operator code is a fixed Python probe beside its scenario, carried with JSON arguments
over the shared SSH seam and run as `sudo -n -- python3 -c <probe> <arguments>`, as
`working_data_probe.py` is. Without the section, every host-side stage skips naming it,
and each observation it requires is unproven.

The route gives the test no reach the deployment under test lacks: the provisioning
service already holds a key that runs code as root on the host. It gives the test its
own route, apart from the service's. The route is the deployment's to provide; until it
is, the run waits (D22).

Rejected:
- an operator procedure between named runs, the target stating each run's phase: the
  phase is the operator's word rather than an observation, a UFW reload is observable
  nowhere, and no heartbeat spans runs, so convergence with an uninterrupted session
  cannot be shown;
- new administrator operations in the provisioning service and the VM operator client
  to re-apply the policy and converge guests: new routes, jobs and client methods, a
  second acceptance boundary, and restarting libvirtd or reloading UFW are no product
  operation, so the restart and reload would still need a route;
- proving the host-side claims only in a privileged container with real `iptables`: it
  leaves libvirtd's start order, `ufw reload` running `after.init`, and live
  convergence unproven on a real host;
- deferring the host-side observations, against D2;
- driving the host-side steps through the provisioning service's existing reach rather
  than a route of the test's own: kept as the fallback should the deployment be unable
  to provide the route (Open Questions), since it needs no new endpoint.

### D19 — `e2e_vm_guest_isolation` extends the real-provisioning scenario's two-guest window

The scenario is a module of its own subclassing `e2e_vm_real_provisioning`'s shared
stages: it makes the same two deals on one host, adds its isolation stages within the
window in which both guests run and the first holds a heartbeat, and shares the
teardown. It runs in no lane, is blocked without the real-provisioning target, carries
a marker of its own in `e2e-tests/pyproject.toml`, and logs each observation (D22) as
made, failed or unproven after its last stage, through
`tests/e2e/roles/helpers/qualification.py`, as the qualification modules do.

Rejected: isolation stages inside `e2e_vm_real_provisioning`, gated on the section,
which would restart libvirtd and alter a guest in the ordinary real-provisioning run
whenever a target names the section, blurring that scenario's evidence; guests created
through the VM operator client with no deal, which have no buyer path for O2 and O8.

### D20 — Convergence is one installed command, proven on a guest planted unconverged

Host preparation installs `vm-setup/files/guest_converge.sh` as
`/usr/local/sbin/arkhai-guest-converge`, runs it, and reports from its output, as it
installs and runs `arkhai-guest-policy`. The command converges every running guest as
D9 says and writes one machine-readable line per guest: its name, whether its port is
isolated, whether its filter applied live or waits for the guest's next start, whether
its saved definition carries both, and the reason for any step that failed. It exits
non-zero only when it could not run at all. Host preparation names each guest the
output reports unconverged; the scenario's operator probe runs the same command and
reads the same lines, so neither caller interprets `virsh` itself.

The proof plants, through the operator route, the state an earlier release left on the
first deal guest, the one holding the heartbeat: its live port's isolation cleared, its
filter detached live, and its saved definition without either. It then runs the
command and checks that the heartbeat's longest gap is at most five seconds, that the
port is isolated, that the saved definition carries both, and that the guest-to-guest
probes are refused again: O8, which every libvirt can plant, since clearing a live
port's isolation and editing a saved definition are always allowed. Whether the filter
is bound live again is O9, observed apart (41 F2). O9 is made only when the fixture
detached the filter live and convergence bound it live again. Where libvirt refuses the
fixture's own live filter removal, the filter was never absent, so the fixture plants
the rest and O9 is unproven, naming the libvirt version; where convergence reports the
filter waiting for the guest's next start, D9's accepted fallback, O9 is unproven
likewise, since nothing was restored live. Neither case records a restoration it did
not observe. Convergence reports the filter live only when the running definition
names it and libvirt lists an active binding of it on the guest's tap; a filter the
live definition names with no binding is reported waiting for the next start, with
the missing binding as its reason (50 F2), and fails O9 rather than leaving it
unproven, since libvirt took the live change and did not refuse it.

Rejected:
- a guest an earlier release actually made, by preparing the host and creating the
  guest with v0.3.0's host kit and images, which needs a second deployment in one run,
  or by a hand-made `virt-install` guest outside any deal, which has no buyer session
  and duplicates the create;
- proving convergence only against faked `virsh` and `bridge`, leaving D9 without
  real-host evidence;
- convergence as Ansible tasks, which the scenario cannot run without
  `ansible-playbook` and the IaC tree, so its proof would exercise other code;
- a script run uninstalled by `ansible.builtin.script`, which the scenario could run
  only by carrying a file of the IaC tree across a package boundary into the harness.

### D21 — The VM target's `guest_isolation` section, and probes attributed by counters

A VM target may state, at version 2, an optional section:

```yaml
REAL_PROVISIONING_TARGET:
  version: 2
  hosts:
    - domain: vm
      host_id: kvm-real-1
      # … connection, access, capacity, listing_shape, management_unit …
      guest_isolation:
        operator:                       # referenced, never copied
          host: 127.0.0.1
          port: 16002
          user: qual-observer
          key_path: /run/secrets/example-observer-key
        private_destinations:           # neither needs to answer
          refused: 10.20.0.7            # not in guest_allowed_private_destinations
          listed: 10.20.0.8             # in it; the scenario confirms it from the chain
```

Guest-side probes are a fixed Python probe run under `sudo` in a guest through the
shared SSH seam: ARP, ICMP and TCP to the other guest, directly and through the
gateway; an ARP claim of the other guest's address; DHCP and DNS; the host's port 22
at `192.168.122.1`; `169.254.169.254`; and the two private destinations. A refusal in
O3 to O5 counts only when the matching policy rule's packet counter, read through the
operator route before and after the probe, rose. The listed destination counts as
forwarded only when its accept counter rose and the guest's packet to it was seen
leaving the host: while the guest probes it, the operator probe, already root, holds a
packet socket on the interface `ip route get <listed>` names and reports whether the
guest's connection attempt to that destination left there, after masquerade. The
counter proves the guest policy admitted the packet; it ends the filter table's
`FORWARD` traversal, but a packet must still pass every other table's chain at that
hook, libvirt's own under its nftables backend among them, and only the egress shows
the host forwarded it (41 F1). Counters are per rule, so the run's guests are expected
to be alone on the host, a precondition the controlled target guarantees and the run
states beside its result. Under direct access a guest-side stage reads its buyer
session's peer address and makes O6 when it is private and outside the guests'
network; otherwise, and under relay access, that stage skips naming the
private-source buyer route it lacks. A VM create masquerades a forwarded buyer
connection to its guest, so a guest reached at its forwarded port sees only the
host's own address on the guests' network: under this create O6 is never made, and
the stage skips naming the masquerade. The scenario reads no buyer's original source
on the host (50 F1).

An absent `private_destinations` skips O5's stages naming it. An older harness meets
the section as an unknown field and refuses it naming the field, as the target model
refuses any.

Rejected: required fields or a target version 3, which fail every existing VM target
for a section one module reads; refusals judged by the absence of a reply, which reads
a destination that does not exist as refused; destinations that must answer, which a
controlled target may not offer; the accept counter alone as forwarding, which proves
the guest policy's decision and not that the host forwarded the packet; relabelling O5
as the policy's admission, which leaves forwarding unobserved on a real host (41 F1);
observing O6 on the host, by a packet watch on the forwarded port or the connection
tracking entry's original source through the operator route, which would make O6
under the masquerade at the cost of another probe operation (50 F1, the owner's
choice).

### D22 — Closeout waits on observations O1 to O5, O7 and O8 being made

The proof's observations:

| # | Observation | Decision |
|---|---|---|
| O1 | ARP, ICMP and TCP from one guest to the other, directly and through the gateway, refused | D7 |
| O2 | An ARP claim of the other guest's address dropped while its buyer still reaches it, and the filter's parameters present in the guest's live definition | D7 |
| O3 | DHCP and DNS pass; another host port refused | D8 |
| O4 | `169.254.169.254` refused | D8 |
| O5 | An unlisted private destination refused; a listed one admitted by its accept rule and seen leaving the host on its routed interface | D8 |
| O6 | A buyer from a private address reaches their guest | D8 |
| O7 | O3 to O5 still hold after a libvirtd restart and after a UFW reload, both jumps first | D8 |
| O8 | A guest planted unconverged — its live port isolation cleared, its saved definition stripped — has its port isolated again and its saved definition carrying the isolation and the filter, its session's longest gap at most five seconds and its probes of the other guest refused again | D9 |
| O9 | The filter the fixture detached live is bound live again by convergence | D9 |

D2's closeout gate requires O1 to O5, O7 and O8 made. O6 may be unproven only for want
of a private-source buyer route, or because the create's masquerade hides the buyer's
address from the guest, which under this create is every direct-access run (D21,
50 F1): while it is unproven, it rests on the forwarded established/related accept's
place ahead of the private-range drops, held by the rendered-chain and native
installer tests, and on O7's evidence that the chain order survives on a real host.
O9 may be unproven only because libvirt refused the fixture's live filter removal, or
because convergence reported the filter waiting for the guest's next start with the
live definition not naming it (D20): until a run makes it, live filter convergence rests on the
static tests faking `virsh`, and on O2's evidence that the filter is bound on a guest
this release created (41 F2). A failed observation, or an unproven one other than O6
and O9 for those reasons, returns the change to implementation. With no target or no operator route, the change
waits at the run rather than proceeding. The run's evidence is supplied by whoever
deploys the target, as a sanitized summary per observation with its run identifier and
the host's libvirt version; raw logs stay in the operator's storage.

Rejected: every observation required, which on a target whose buyers reach guests only
through a relay holds closeout on a topology change outside this repository; recording
whatever ran and closing out, against D2; a fixture required to detach the live filter
before O8 can be made, which holds closeout on a libvirt that permits live filter
changes; O8 made with a filter recorded as waiting for its next start, or never
removed, which reports a restoration nobody observed (41 F2).

### D23 — Removing the older per-port guest rules is a compatibility path, retired on schedule

Host preparation deletes, from a host that holds them, the guest port-22 drops and logs,
`ufw allow in on virbr0 from 192.168.122.0/24`, and `vm-network-isolation.service` with
its script, which only a host prepared by an earlier release holds. That is an upgrade
branch adopting state an older release wrote, so it carries a row in "Compatibility to
retire", retiring with D6's and D9's. Afterwards a host still holding the old rules keeps
them, behind the policy's first-position jumps, which decide every guest packet first.

Rejected: treating the removal as permanent cleanup, against D16's definition; leaving
the old rules in place, which leaves the printed host state untrue on upgraded hosts and
a latent accept should a jump ever be lost.

### D24 — The remaining work is two sessions, then a round for the real-host run

See "Implementation cadence".

## Implementation cadence

- **Round 1 — host-key verification**, two sessions in order, done:
  1. the `ssh` connection at version 3 with `host_keys`, the codec, the v2-to-v3
     migration and its pending-adoption flag, the host definitions document and its
     export, the INI import keeping pins, and the family client;
  2. the runner's per-job `known_hosts` and host variables, the check before a job's
     start with adoption, the capture route, the connectivity result's `host_key`,
     readiness, and the e2e helpers.
- **Round 2**, three sessions:
  1. guest isolation: the interface definition for every `virt-install` site, the host
     kit's guest policy chains with `guest_allowed_private_destinations`, and correcting
     the README's and the host kit's claims (done);
  2. convergence and the proof's code: the convergence command and its host-preparation
     task (D20), the target's `guest_isolation` section (D21), and
     `e2e_vm_guest_isolation` with its probes and per-observation outcomes (D19), with
     their static and unit tests;
  3. the administrator stance: the API-credits storefront's negotiation reads and the
     storefronts' refusal tests.
- **Round 3 — the real-host run**, one session: recording the deployment's sanitized
  per-observation evidence from `e2e_vm_guest_isolation` (D22) and fixing what the run
  finds, reviewed on its own.
- **Closeout** writes the promotion: the specifications and companions, `ARCHITECTURE.md`,
  the engineering and repository guidance and the release handbook's table (D16), the
  operator handbook, the quickstarts, `DEPLOYMENT_AND_CONFIG.md`, and the roadmap.

Host-key verification is reviewed alone because it carries the most risk: a security
property, and Ansible's ordering of its arguments. The real-host run has a round of its
own because it waits on the deployment's target and operator route, which round 2's
review need not wait for, and because a failed observation returns the change to an
implementation round (D22).

## Promotion text

The owner accepted these as drafted; closeout writes them.

### The engineering guidance's new `retiring-compatibility.md`

```markdown
---
tags: [engineering, versioning]
---

# Retiring compatibility

How code that exists only for older deployments is added together with its end,
recorded where releases are decided, and removed. Which deployments are owed
compatibility at all is
[Versioning, "Compatibility is owed to what has been deployed"](versioning.md#compatibility-is-owed-to-what-has-been-deployed);
how a stored form stays readable while it is retained is
[Persistence, "A retained record stays readable"](persistence.md#a-retained-record-stays-readable).

## What a compatibility path is

A compatibility path is code, configuration, or documentation that exists only
because a deployment may still hold an older form: a reader of a stored
representation no writer produces any longer, an upgrade branch that adopts
records an older release wrote, a fallback accepting an older wire form or
configuration key, a refusal naming a retired setting's replacement, a stage of
a staged rename. Code serving the forms current releases write is not one,
however old it is. The tests and fixtures that hold a path are part of it.

## Every path is added with its retirement

The unit of work that adds a compatibility path states, in the same unit of
work, when the path retires. The statement names:

- **what retires**: the code, its tests and fixtures, the configuration only it
  reads, and every document describing it;
- **when**: a release, counted from the release that first carries the path,
  such as "the second release after the one that first carries it", or a named
  version together with that count, whichever is later, so a renumbered release
  does not strand it. A condition that cannot be checked when a release is
  prepared, such as "once nothing uses it", is not a retirement;
- **what a deployment still holding the old form meets afterwards**: a refusal
  naming the form and how to recover, or the path's strict successor, never the
  old form silently read as something else;
- **how an operator learns, before then, whether a deployment still holds the old
  form**, where the service can tell: a status or readiness report naming what
  remains.

A path whose retirement cannot be stated is a design question, not a
compatibility path: settle what the system does for that form permanently and
write it as current behaviour.

## Retirements are recorded where releases are decided

A repository keeps one list of pending retirements, read by whoever prepares a
release. The unit of work adding a path adds its row; the one retiring it removes
the row. The list holds only what is pending: what retired is recorded by the
version numbers ([Versioning, "The version numbers are the record"](versioning.md#the-version-numbers-are-the-record)).
A comment does not carry the schedule, because a comment describes the code as it
is, and a date in one is a plan that no release step reads.

## A retirement falls due

Preparing a release, each row due at it is retired before the release candidate
is taken, or moved to a later release with its reason recorded on the row. No row
is left silently past its release. A row moved a second time is reconsidered:
either the path serves a form that is in fact still current, and is rewritten as
current behaviour, or its retirement depended on something that cannot be
observed, and is restated.

## Retiring removes everything the path carried

A retirement removes, in one unit of work, the path's code, its tests and
fixtures, the configuration keys only it read, and every document describing it,
and bumps each package it changes as an incompatible change, which it is for a
deployment still holding the old form ([Versioning](versioning.md)). A path is not
due while removing it would leave a deployment without the recovery its row
names.

## A staged change names each stage's release

A field renamed or retired in stages
([Versioning, "A field may be renamed or retired in stages"](versioning.md#a-field-may-be-renamed-or-retired-in-stages))
names the release of each later stage when its first stage lands, and each later
stage is a row.
```

`versioning.md` links it from "Compatibility is owed to what has been deployed" and
"A field may be renamed or retired in stages", and the engineering README's
description of the `versioning` tag gains "and retiring compatibility".

### `docs/guidance/repository/package-versions.md`, after "Compatibility is owed to what a release has shipped"

```markdown
## Compatibility paths retire on a schedule

This repository retires its compatibility paths as
[`retiring-compatibility.md`](../engineering/retiring-compatibility.md) says, and
its list of pending retirements is the release handbook's
["Compatibility to retire"](../../release-handbook.md#compatibility-to-retire).
A change adding a path adds its row at closeout, with the rest of its promotion;
a change retiring one removes the row. A retirement names a marketplace release
counted from the release that first carries the path, and may name a version
beside the count, whichever is later, since a planned minor release can become a
major one. A migration is not a row: the migration floor absorbs migrations when
a release is cut ([the release handbook, "The migration floor"](../../release-handbook.md#the-migration-floor)).
```

### `docs/release-handbook.md`, after "The migration floor"

```markdown
## Compatibility to retire

Code kept only for older deployments retires at a stated release
([`package-versions.md`, "Compatibility paths retire on a schedule"](guidance/repository/package-versions.md#compatibility-paths-retire-on-a-schedule)).
Before loading a release candidate, retire on `main` every row due at the release
it will become, removing what the row names, or move the row to a later release
with its reason in the row. When the release is cut, record it in `First
released in` for every row it is the first to carry.

| Compatibility path | First released in | Retires in | What retiring removes | A deployment still holding the old form |
|---|---|---|---|---|
| Adoption of hosts registered before host keys were pinned | — | 0.3.3, or the second release after the one first carrying it, whichever is later | The `hosts` row's pending-adoption flag; the `accept-new` path of the check before a job's start and of the connectivity check; readiness's list of pending hosts | Such a host is unpinned: its jobs are refused until an operator captures or states its key. Readiness lists pending hosts before then |
| Convergence of guests created before guest isolation | — | 0.3.3, or the second release after the one first carrying it, whichever is later | The host kit's `arkhai-guest-converge` command and the host-preparation step installing and running it, which set running guests' bridge isolation and filter | A guest it never converged keeps a port that is not isolated until it is torn down. The host kit reports such guests before then |
| Removal of the per-port guest rules hosts were prepared with before the guest policy | — | 0.3.3, or the second release after the one first carrying it, whichever is later | Host preparation's step deleting the old guest port-22 drops and logs, `ufw allow in on virbr0 from 192.168.122.0/24`, and `vm-network-isolation.service` with its script, and that step's tests | The old rules stay on the host, behind the guest policy's first-position jumps, which decide every guest packet first; an operator may delete them by hand |
```

The handbook's introduction names the section; "Loading a release candidate" gains a
first step, "Retire every row of [Compatibility to retire](#compatibility-to-retire)
due at this release, or move it"; and "Cutting a release" gains, at its second step,
"and on `main`, record the release in `First released in` for each row it first
carries; confirm no row names this release in `Retires in`".

### `docs/development/ARCHITECTURE.md`, "Shared vocabulary and identities", after "Authenticated service boundaries"

```markdown
### The administrator's reach

The administrator is the operator of the service it calls, and what it may reach
follows from what that service holds. On a route that acts on resources the
operator owns, the administrator is admitted beside any role the route names:
every route of the provisioning service and of a site authority is such a route,
since hosts, leases, capacity and the ledger are all the operator's, and a role
that can administer the whole authority but not one named route only obstructs
the person holding it. On a route whose authorization binds the caller to a deal
as a party — a buyer's negotiation and settlement routes, a seller acting as
counterparty, a service peer's callback — the administrator is never authorized
as that party. It acts there only through administrator operations, which record
it as the administrator, so a party's history holds only what that party sent. A
storefront's own records of its deals, such as bare-metal lease-ready evidence,
are the storefront operator's, and its administrator reads them.

Each service states its form in its specification and holds it with a test: the
provisioning service refuses, when it assembles its route table, a route that does
not admit `admin`; `kit/site` admits `admin` on every site contract without
enumerating it; each storefront refuses an administrator's request on its party
routes and admits it on its administrator routes. How an administrator
authenticates is separate from what it reaches: the registry's administrator
presents a bearer key, and the API-credits service accepts a shared administrator
key when signing is not configured.
```

## Risks / Trade-offs

- **An operator's Ansible configuration.** Verification rests on host variables
  outranking configuration. A test runs Ansible's own command builder against an
  operator file that turns checking off and states `ssh_args`.
- **The guest policy's place.** D8's chains must be reached before UFW's and libvirt's
  accepts, and stay first when either reloads its rules; the host kit re-asserts the
  jumps, and the real-host proof checks the policy after both reloads.
- **nwfilter on sellers' hosts.** `clean-traffic` needs libvirt's nwfilter driver,
  over ebtables and iptables or their nft shims. A host without it fails host
  preparation by name rather than running guests unfiltered.
- **Deployed hosts' first answer.** D6 trusts it once, as those hosts have been trusted
  on every contact; an operator wanting no unchecked contact captures or states keys
  instead.
- **One more handshake per job.** D5's check before the start adds an SSH connection to
  every job.
- **Private-address topologies.** A development topology whose guests need private
  destinations sets `guest_allowed_private_destinations`; no lane runs real VMs.
- **The real-host proof's prerequisites.** Closeout waits on a controlled target and on
  the deployment providing the operator route (D18, D22), both outside this repository.
  A private-source buyer (O6) stays unproven under the create's masquerade, and on a
  target whose buyers reach guests only through a relay; its replies' passage rests on
  the static chain-order tests and O7. Live filter restoration (O9) may stay unproven
  on a host whose libvirt refuses live filter changes.

## Open Questions

- **The host-side steps without an operator route.** If the deployment cannot provide
  the target's operator route, how the proof's host-side stages run through the
  provisioning service's existing reach, with no new endpoint (D18). Revisit when the
  deployment reports that the route cannot be provided.
- **A private-source buyer observed on a real host.** Revisit when a guest's buyer
  connection is no longer masqueraded, or a goal needs O6 made, by reading the buyer's
  original source on the host (D21, D22, 50 F1).
- **A live filter restored on a real host.** Revisit when a target's libvirt both
  removes and applies a running guest's filter live, and make O9 (D20, D22).

- **A private network for one buyer's guests.** Revisit when a goal sells several
  guests to one buyer as a cluster (D10).
- **A keyring whose private keys a KMS holds.** Part of the deferred credential work;
  revisit when a deployment requires that the provisioning container hold no
  long-lived key material (D11).
