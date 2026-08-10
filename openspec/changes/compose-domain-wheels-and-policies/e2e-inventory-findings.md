# E2E inventory failure — findings as of run 31429964727

## Established from logs

1. The capacity poller signature bug is fixed — `poller cycle failed` count is 0,
   and the compose log shrank from 1,005,688 to 184,303 bytes. That warning was
   ~800KB of the previous log, firing on every cycle on both storefronts.

2. The five failures are unchanged: `5 failed, 53 passed, 42 skipped`.

3. The site authority starts empty and stays empty for VM resources:

       compute_provisioning_service.app_runtime - INFO -
         Inventory seeding: no inventory source configured — starting with
         empty host registry
       compute_provisioning_service.app_runtime - INFO -
         Pool-definitions import: no pool_definitions

   The only resource it ever registers is `weather-quota`, from apicredits.
   No `Registered resource` line for any VM resource, in the whole run.

4. `GET /api/v1/capacity/snapshot` returns 200 OK, 36 times. The authority is
   reachable and answering — the earlier "two stores never met" framing was
   wrong. It answers; it has nothing to say about VM resources.

5. The storefront's own path works throughout: `Resource import: 1 imported,
   0 failed` and six `Published listing` lines. Publication reads local tables.

## Why the authority is empty

`inventory_path` defaults to
`/opt/domains/vms/provisioning/iac/ansible/inventory/hosts`, inside the volume
the e2e stack mounts. The repository contains only `hosts.example`; the real
`hosts` is operator config and its own header says it is gitignored, so it does
not exist in CI.

`[kvm_hosts]` in that file is, per its own comment, "the group the storefront's
VM `attribute.vm_host` column in `resources.csv` resolves against", and the e2e
seed rows carry `attribute.vm_host=kvm1`.

## The unverified link

Whether an empty **hosts** table is what makes the **capacity snapshot** empty
for VM resources. Hosts and resources are different tables; the inference is that
capacity buckets derive from hosts' declared `gpus=<count>`. I did not trace the
snapshot handler to confirm it — the route is not in
`provisioning/compute/service/src` under an obvious name.

Confirm before acting: find the `/api/v1/capacity/snapshot` handler and check
whether its result derives from the hosts table, from resource pools, or from a
separately registered resource ledger.

## If the link holds

The fix is a CI inventory fixture: a committed `hosts` file for the e2e stack
with `kvm1` in `[kvm_hosts]`, mounted or pointed at by `inventory_path`. Small,
in scope, and not POOLS-9 — the migration question does not arise if the
authority simply has no inventory because nobody gave it any.

If it does not hold, the next question is what populates the authority's resource
ledger, and whether anything in the VM path was ever meant to call it — which is
the POOLS-9 question.
