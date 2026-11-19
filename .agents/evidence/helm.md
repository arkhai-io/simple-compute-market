# The Helm evidence kind

The `helm` kind shows that the tree under validation deploys: its images built, the
chart installed into the change's own namespace on the local cluster, the chart's
render checks passing, and the end-to-end scenarios the default charts can serve
passing there. It shares the machine's Docker daemon and CPU with the `local` kind,
and the node's memory with every other change's validation.

## What it runs

It runs in the change's own namespace, `validate-<change>`, a name longer than a
namespace allows cut and ending in a short hash, which its summary names. The kube
context is `HELM_CONTEXT`, `docker-desktop` unless the owner's environment names
another; the kubeconfig must hold it, and the kind pins it for its own commands,
leaving the machine's selected context alone, so a production context selected there
is never deployed to. With `HELM_ALL_SCENARIOS=1` in the owner's environment it runs
every pipeline scenario, not only the served list. Both are values of the owner's
machine and reach the kind through the environment; validation never passes one.

1. **Preflights**, before anything slow: the kube context; the VM and bare-metal
   storefront environments the chart-to-loader checks run in, which the checkout's
   bootstrap creates, so their absence is environmental, its remedy that bootstrap
   (`make init`); the Docker daemon; a
   `Ready` node; Foundry's `cast`, which derives the namespace's Secrets; a warning if
   the Docker credential helper does not answer; and the capacity preflight — a
   warning when no metrics source answers (`metrics`), so no memory is recorded, a
   warning when `helm/validation-capacity.toml` records no figure (`capacity`), so
   the check is skipped, and otherwise the namespaces running the validation release,
   plus this one, times the figure, against the node's allocatable memory.
2. **The images**: the wheelhouse cleared (`dist-clean`), so every wheel built is the
   tree's own rather than one another branch left in `.dist`; the images built under
   the change's own tags; and both storefront environments reinstalled from the
   wheelhouse.
3. **The render checks**, with the chart-to-loader checks running this tree's code; a
   skipped check fails the kind.
4. **The release replaced**: workloads an earlier run left up scaled to zero, its
   pods and volumes deleted and gone, the namespace's Secrets created, the release
   upgraded in place from zero — or uninstalled and installed when the chart refuses
   the upgrade, a warning on the `deploy` step — resumed, and each workload rolled
   out.
5. **The served scenarios**, as a pod in the namespace (`helm test`), reaching
   services by name; then the release's storefront check pods, each its own step —
   `payments check <pod>` and `mediation check <pod>` — passing only on the pod's own
   exit status of 0, their logs `<pod>.log` and their records in `summary.json`'s
   `evidence.payments_checks` and `evidence.mediation_checks`.
6. **Afterwards**, once the release has been touched, whatever the deploy or the
   scenarios did: the namespace's evidence kept and its workloads scaled to zero —
   only the scale-down when the checkout no longer holds the tree. An attempt that
   stops before it touches the release, at a preflight, the build, or the render
   checks, keeps no namespace evidence.

## Reading its evidence

Each attempt is a directory named by the UTC time it started,
`%Y%m%dT%H%M%S.%fZ`, so path order is time order and the last attempt is the
current one. It holds `summary.json` and one log per step, as the `local` kind's
does, the summary also naming the namespace, and prints the summary as text as it
ends, its first line `helm evidence for the tree <the tree's first twelve
characters>, attempt <attempt>: PASSED` or `FAILED`. The tree is checked before,
after, and between steps the same way, and a step failing with "the worktree
changed" or "HEAD is now …" describes no one tree, so validation stops.

The summary lists the pipeline scenarios not run because the charts cannot serve
them; those are never passes. The attempt also keeps the namespace's evidence:

- the scenario pod's log and exit status — `scenarios.log`, `scenarios.exit`, and
  `evidence.scenarios` in `summary.json` — its step passing only on the pod's own exit
  status of 0;
- every pod's log under `pods/`, with a restarted container's previous log
  (`pods/<pod>.previous.log`), and each pod's status (`pods.json`);
- the namespace's events (`events.log`) and the nodes' (`node-events.log`);
- the validation release's workloads in every other namespace, with their replicas, at
  the preflight and at the end (`evidence.other_namespaces_at_start`,
  `evidence.other_namespaces`);
- the rendered requests and limits (`resources.txt`), and whether they changed since
  the namespace's previous validation (`evidence.resources.changed`), naming that
  validation's file;
- the namespace's sampled memory, when a metrics source measured it
  (`memory.peak_bytes`).

## Telling its failures apart

Read a failing step's log, then the state it points at: the pod logs under `pods/`
and the events.

**Memory.** Another change's validation may run on the same node, and two capacity
preflights can pass together, so a pod can still fail for memory. Classify such a
failure from the attempt's evidence, never from the symptom alone, since a commit that
raises a request, lowers a limit, or leaks fails the same way:

- **Environment**, when a pod could not be scheduled for memory — `events.log` has
  `FailedScheduling` naming insufficient memory — or was evicted for memory —
  `events.log` has `Evicted` naming the node low on memory, which the node's memory
  pressure in `node-events.log` confirms when its events were still kept — while
  another change's namespace had the validation release up: a `validate-…` namespace
  other than this one with a replica above zero in
  `evidence.other_namespaces_at_start` or `evidence.other_namespaces`. Those are read
  at the preflight and at the end, not at the failure, so say which showed it. The
  owner's own release in `default` is not another change's validation. The remedy is
  scaling that namespace's release to zero (`kubectl scale --namespace <namespace>
  --replicas=0 deployments,statefulsets --selector
  app.kubernetes.io/instance=<release>`), or a new attempt once its validation has
  ended. When the commit also changed the rendered requests or limits
  (`evidence.resources.changed`), say so beside the remedy: the new attempt with
  nothing else running tells contention from the commit's own demand, and a pod that
  again cannot be scheduled then is the commit's.
- **Commit**, when a container was killed at its own limit — `pods.json` gives
  `OOMKilled` as a container's last or current termination reason, `resources.txt`
  gives that container a memory limit, and `node-events.log` shows no system
  out-of-memory kill or memory pressure on the node at the time; read its previous
  log for what it was doing — or when, outside the case above, the commit changed the
  rendered requests or limits (`evidence.resources.changed` is true: compare
  `resources.txt` with the previous validation's file it names).
- **Unknown** otherwise — an `OOMKilled` with no limit or beside the node's own memory
  pressure, contention only from `default`, or evidence an `evidence` warning left
  empty.

**Capacity.** A `capacity` step failed with a detail beginning `environmental:` is the
preflight finding the release would not fit: environmental, its remedy the one the
detail gives. A `capacity` failure without that prefix — an unreadable capacity file,
or the cluster's memory or other namespaces that could not be read — is diagnosed like
any failure.

**Volumes.** A `volumes gone` step whose detail says a volume still exists after its
deletion names a volume that outlived it: environmental, its remedy deleting it. One
that failed because the cluster could not be read is diagnosed like any failure.

**Warnings** are not failures. Each warning step means:

- `credential helper`: image builds may fail to look up registry credentials;
- `metrics`: no memory recorded;
- `capacity`: the capacity check skipped;
- `deploy`: the upgrade was refused, and the release uninstalled and installed;
- `memory`: a memory sample failed;
- `evidence`: that evidence was not kept, and its key is empty;
- `scenario pod`: its exit status could not be read;
- `payments check` or `mediation check`: the release renders no such check pod, so
  no storefront's access is shown, or a check pod's exit status could not be read.

**Every scenario.** When the owner's environment set `HELM_ALL_SCENARIOS=1` — the
summary then lists no scenario as not run against Helm — the scenarios outside the
served list (`HELM_SCENARIOS` in `scripts/validate_slice.py`) ran to test the list,
not the commit, and the `e2e` step fails whenever one of them does. Judge the kind by
the served scenarios alone, and list each other scenario with what it showed: failed
because the charts do not serve it (expected), failed for another reason (diagnosed
like any failure), or passed (it can join the list). A list that should grow is
reported about the validation.

## Its section of the record

```markdown
## Helm

Namespace: <the summary's namespace>. Scenario pod: <pod>, exit <status>. Peak
memory: <bytes, or none measured>. Warnings: <each warning step and what it means,
or none>.

| Attempt | Step | Result | Duration |
|---|---|---|---|

Not run against Helm: <scenario> — <what the charts do not provide>; …
```

Every warning step goes there, with what it means for the run, and, with every
scenario run, each scenario outside the served list with what it showed. Validation's
report names the scenarios not run against Helm.

## Its cleanup

Its cleanup, at archive cleanup, writes one tracked file:
`helm/validation-capacity.toml`, the memory one release needed as the change's latest
validation measured it, with `measured_at` and the change's name, replacing any
earlier figure. It writes it only when that validation measured memory; otherwise it
leaves the file as it is and says why. Archive cleanup commits the file alone, the
message naming the change and the figure. The figure is advisory and overwritten
often, so a merge conflict over it keeps the figure whose `measured_at` is later.

The cleanup then removes the change's namespace, with its release, volumes, and
Secrets, and the images its validation built under the change's tags; a namespace or
image already gone is no failure. When Docker or the cluster does not answer, or an
image is in use, the cleanup fails, and is rerun once the cause is gone.

## In a plan

The scenarios this kind serves are the pipeline's, named as the pipeline guide says;
a scenario the charts cannot serve is reported as not run here, never as passed.
