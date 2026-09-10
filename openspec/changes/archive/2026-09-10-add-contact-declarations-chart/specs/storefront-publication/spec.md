## ADDED Requirements

### Requirement: Chart publication enrollment is explicit and mutually exclusive

The bare-metal chart SHALL expose default-null `contactDeclarations` and
`contactOffers` with the same existing public ConfigMap and independent registry
URL, authority, principal and API-key Secret references. Both non-null modes SHALL
fail validation/rendering. The general mode SHALL emit only the general declaration
startup path, while the historical mode SHALL retain its legacy path. The general
mode's ConfigMap and registry API-key references SHALL name a valid Kubernetes
object and a data key the pod can project as a file, excluding the keys Kubernetes
reserves for directory traversal; the historical mode SHALL keep its existing
nonempty-reference checks, so configurations that render today are not newly
refused. Neither mode SHALL carry declaration bodies, shareable text, private
routes or credentials in chart values. The installed runtime SHALL remain the
declaration validation authority.

#### Scenario: General publication is explicitly configured

- **WHEN** `contactDeclarations` supplies valid references and `contactOffers` is null
- **THEN** the chart mounts the public file at the emitted general startup path,
  excludes site bindings and preserves publication storage and startup guards
- **AND** delivery is projected only from an independently explicit delivery Secret

#### Scenario: Modes conflict or a general reference is unusable

- **WHEN** both modes are supplied, or `contactDeclarations` omits a required
  reference or names a ConfigMap or Secret entry Kubernetes cannot address, including
  a reserved data key such as `.` or one beginning with `..`
- **THEN** the chart refuses before a usable manifest is emitted

#### Scenario: Historical chart configurations render

- **WHEN** an existing physical, runtime-only or legacy contact configuration is rendered
- **THEN** complete rendered bytes remain unchanged, including delivery permutations
- **AND** neither null publication hook enrolls startup in file publication
- **AND** `contactOffers` and the delivery reference keep their prior acceptance,
  including reference names and keys the general hook refuses
