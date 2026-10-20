## ADDED Requirements

### Requirement: A deployment does not wait on a service's dependencies

A chart MUST NOT hold a service back with init containers that wait for or validate its
external dependencies, such as a registry, a chain, or a site. The service MUST start
while a dependency is unreachable, report the dependency as degraded in its status while
its process health check answers, and recover without a restart when the dependency
answers.

#### Scenario: The VM storefront starts before its registry and chain

- **WHEN** the VM storefront starts while its registry and its chain are unreachable
- **THEN** it starts and answers its health check, its status reports Alkahest unready
  with a reachability blocker and a failed publication cycle, and both recover once the
  dependencies answer

#### Scenario: A storefront chart renders

- **WHEN** the VM or bare-metal storefront chart is rendered
- **THEN** its Deployment carries no init container that waits on a dependency

### Requirement: Helm test pods carry no workload selector labels

A Helm test pod MUST NOT carry every selector label of any workload its release deploys,
so that selecting a workload's pods by label never returns a test pod. A test pod MUST
carry the release's instance label and `app.kubernetes.io/component: test`, and MUST NOT
carry `app.kubernetes.io/name`.

#### Scenario: A registry's pods are selected

- **WHEN** an operator selects the registry Deployment's pods by its selector labels after
  `helm test` has run
- **THEN** only the registry's own pods are returned

#### Scenario: Both topology releases are rendered

- **WHEN** both local topology releases are rendered
- **THEN** no Pod annotated `helm.sh/hook: test` carries all of any rendered Deployment's
  `matchLabels`
