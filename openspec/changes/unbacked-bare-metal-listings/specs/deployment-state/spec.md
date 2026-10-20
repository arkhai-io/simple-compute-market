## ADDED Requirements

### Requirement: A deployment does not wait on a service's dependencies

A chart MUST NOT hold a service back with init containers that wait for or validate its
external dependencies, such as a registry, a chain, or a site, and a service MUST NOT
wait for one, or refuse to start because one is unreachable, in its own startup. The
service MUST start while a dependency is unreachable, report the dependency as degraded
in its status while its process health check answers, and recover without a restart when
the dependency answers. A chart whose service starts slowly MUST give it a startup probe,
so that a slow start is not judged by its liveness probe.

#### Scenario: The VM storefront starts before its registry and chain

- **WHEN** the VM storefront starts while its registry and its chain are unreachable
- **THEN** it starts and answers its health check, its status reports Alkahest unready
  with a reachability blocker and a failed publication cycle, and both recover once the
  dependencies answer

#### Scenario: A storefront starts before its site or service

- **WHEN** the VM storefront starts while its provisioning service is unreachable, or the
  API-credit storefront while its credits service is
- **THEN** it starts and answers its health check, calls to that service fail retryably,
  and they succeed once it answers, without a restart

#### Scenario: A storefront chart renders

- **WHEN** the VM or bare-metal storefront chart is rendered
- **THEN** its Deployment carries no init container that waits on a dependency, and its
  container carries a startup probe

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
