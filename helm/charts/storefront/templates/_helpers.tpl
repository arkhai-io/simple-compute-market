{{/*
helm/charts/storefront/templates/_helpers.tpl
*/}}

{{- define "storefront.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "storefront.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "storefront.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "storefront.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "storefront.selectorLabels" -}}
app.kubernetes.io/name: {{ include "storefront.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Resolve the full image reference for the agents container.
Supports an optional global.imageRepository passed down from the parent.
*/}}
{{- define "storefront.image" -}}
{{- $repo := .Values.image.repository -}}
{{- if and (not $repo) .Values.global -}}
  {{- $repo = .Values.global.imageRepository -}}
{{- end -}}
{{- $name := .Values.image.name -}}
{{- if $repo -}}
  {{- $name = printf "%s/%s" $repo $name -}}
{{- end -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" $name .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" $name .Values.image.tag -}}
{{- end -}}
{{- end }}

{{/*
Compose the registry URL from global.registry.host and global.registry.port.
*/}}
{{- define "storefront.registryUrl" -}}
{{- $host := default (printf "%s-registry" .Release.Name) .Values.global.registry.host -}}
{{- printf "http://%s:%d" $host (int .Values.global.registry.port) -}}
{{- end }}

{{/*
Compose the provisioning service URL from global.provisioning.{host,port}.
*/}}
{{- define "provisioning.url" -}}
{{- printf "http://%s:%d" .Values.global.provisioning.host (int .Values.global.provisioning.port) -}}
{{- end }}

{{/*
Compose the agent's externally-advertised base URL from the agent's
Service DNS + port. This is what the storefront advertises on its
registry listings (and what buyers dial to reach it).
Argument: dict with `root` and `agent`.
*/}}
{{- define "storefront.agentBaseUrl" -}}
{{- $svc := include "storefront.agentFullname" . -}}
{{- printf "http://%s:%d/" $svc (int .agent.port) -}}
{{- end }}

{{/*
A values file's `null` removes what it names, whether or not Helm's merge removed
it: under the supported Helm release, a parent's `null` for a subchart is dropped
only where the subchart's own defaults define the key, and every agent and every
key under one comes from the parent or an overlay. So the chart removes them
itself before any template reads an agent, and an agent renders as it would had
the removed key never been stated. See openspec/specs/deployment-state/spec.md,
"A storefront chart passes service configuration through".

`storefront.dropNulls`: remove, in place, every key whose value is `null` from the
mapping `.`, at every depth, inside list elements too. A list element is a value
rather than a key, so a `null` element stays.
*/}}
{{- define "storefront.dropNulls" -}}
{{- if kindIs "map" . -}}
  {{- range $key, $value := . -}}
    {{- if kindIs "invalid" $value -}}
      {{- $_ := unset $ $key -}}
    {{- else -}}
      {{- include "storefront.dropNulls" $value -}}
    {{- end -}}
  {{- end -}}
{{- else if kindIs "slice" . -}}
  {{- range $item := . -}}
    {{- include "storefront.dropNulls" $item -}}
  {{- end -}}
{{- end -}}
{{- end }}

{{/*
`storefront.agents`: the chart's agents with every `null` removed, set by name into
the mapping `into`: a `null` agent is dropped, and each other agent is a copy with
its `null` keys removed at every depth. An agent map naming no agent once they are
removed is refused, as the values schema refuses an empty one: a release running no
storefront agent disables the storefront instead. An agent stating no port or no
identity, once its nulls are removed, is refused naming it: the chart has neither to
default to, and every agent's container, probes, Service, and credential use them.
Argument: dict with `root` (the chart root) and `into` (an empty dict).
*/}}
{{- define "storefront.agents" -}}
{{- $into := .into -}}
{{- range $name, $entry := (.root.Values.agents | default dict) -}}
  {{- if not (kindIs "invalid" $entry) -}}
    {{- $agent := deepCopy $entry -}}
    {{- include "storefront.dropNulls" $agent -}}
    {{- range $key := list "port" "identity" -}}
      {{- if not (hasKey $agent $key) -}}
        {{- fail (printf "storefront agent %s states no %s" $name $key) -}}
      {{- end -}}
    {{- end -}}
    {{- $_ := set $into $name $agent -}}
  {{- end -}}
{{- end -}}
{{- if not $into -}}
  {{- fail "storefront agents names no agent once its nulls are removed; a release runs at least one, or sets the umbrella's storefront.enabled false to run none" -}}
{{- end -}}
{{- end }}

{{/*
Per-agent fullname: {fullname}-{agent.name}, the agent's name being its key
under agents:.
Used as the Deployment / Service / Secret object name.
Argument: dict with `root` (the chart root) and `agent` (one agent, with its
name).
*/}}
{{- define "storefront.agentFullname" -}}
{{- printf "%s-%s" (include "storefront.fullname" .root) .agent.name | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/*
Per-agent secret name. Honors agent.secret.secretName when set, else
auto-generates from the agent fullname.
*/}}
{{- define "storefront.agentSecretName" -}}
{{- if .agent.secret.secretName -}}
{{- .agent.secret.secretName -}}
{{- else -}}
{{- include "storefront.agentFullname" . -}}
{{- end -}}
{{- end }}

{{/*
Per-agent PVC name. Used as the volume backing the SQLite agent.db
mount at persistence.mountPath. Stable across releases so reinstalls
can rebind existing state.
*/}}
{{- define "storefront.agentPvcName" -}}
{{- printf "%s-data" (include "storefront.agentFullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/*
Per-agent ConfigMap name — non-sensitive runtime config lives here.
Mirrors agentSecretName: honors agent.configMapName, else auto-generates from
the agent fullname.
*/}}
{{- define "storefront.agentConfigMapName" -}}
{{- if .agent.configMapName -}}
{{- .agent.configMapName -}}
{{- else -}}
{{- printf "%s-config" (include "storefront.agentFullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{/*
The agent's Alkahest address book, as JSON for fromJson: `configMapName` (empty
mounts nothing), `key`, and `mountPath`, each defaulted where the agent's
alkahestAddressBook does not state it.
*/}}
{{- define "storefront.agentAddressBook" -}}
{{- $book := .alkahestAddressBook | default dict -}}
{{- toJson (dict
  "configMapName" ($book.configMapName | default "")
  "key" ($book.key | default "alkahest_addresses.json")
  "mountPath" ($book.mountPath | default "/etc/arkhai/alkahest")) -}}
{{- end }}

{{/*
Key lookup as the storefront's loader does it. Dynaconf matches configuration
keys case-insensitively at every level, so every key the chart reads or writes
is matched the same way; otherwise `Port` or `registry.URLS` would slip past a
check and sit beside the value the chart writes.

`storefront.foldedKey`: the key under which `doc` holds `name` (lowercase),
in whatever spelling it was written, or "".
*/}}
{{- define "storefront.foldedKey" -}}
{{- $found := "" -}}
{{- range $key, $_ := .doc -}}
{{- if eq (lower $key) $.name -}}{{- $found = $key -}}{{- end -}}
{{- end -}}
{{- $found -}}
{{- end }}

{{/*
`storefront.foldedMap`: the mapping `doc` holds under `name`, as JSON for
fromJson, or {} when absent. JSON keeps every value's type through the round
trip.
*/}}
{{- define "storefront.foldedMap" -}}
{{- $key := include "storefront.foldedKey" . -}}
{{- $value := dict -}}
{{- if $key -}}{{- $value = index .doc $key | default dict -}}{{- end -}}
{{- toJson $value -}}
{{- end }}

{{/*
Refuse a mapping, at any depth, that states one key in two spellings: the
loader would merge them in an order nobody chose.
Argument: dict with `agent` (name), `path` (dotted, for the message), `value`.
*/}}
{{- define "storefront.refuseFoldedDuplicates" -}}
{{- $agent := .agent -}}
{{- $path := .path -}}
{{- if kindIs "map" .value -}}
  {{- $seen := dict -}}
  {{- range $key, $item := .value -}}
    {{- $folded := lower $key -}}
    {{- if hasKey $seen $folded -}}
      {{- fail (printf "storefront agent %s %s states both %q and %q; state one" $agent $path (index $seen $folded) $key) -}}
    {{- end -}}
    {{- $_ := set $seen $folded $key -}}
    {{- include "storefront.refuseFoldedDuplicates" (dict "agent" $agent "path" (printf "%s.%s" $path $key) "value" $item) -}}
  {{- end -}}
{{- else if kindIs "slice" .value -}}
  {{- range $index, $item := .value -}}
    {{- include "storefront.refuseFoldedDuplicates" (dict "agent" $agent "path" (printf "%s[%d]" $path $index) "value" $item) -}}
  {{- end -}}
{{- end -}}
{{- end }}

{{/*
The first registry URL the agent's storefront uses: the first configured URL,
else the internal registry's.
*/}}
{{- define "storefront.effectiveRegistryUrl" -}}
{{- $registry := include "storefront.foldedMap" (dict "doc" (.agent.config | default dict) "name" "registry") | fromJson -}}
{{- $urlsKey := include "storefront.foldedKey" (dict "doc" $registry "name" "urls") -}}
{{- if $urlsKey -}}
{{- first (index $registry $urlsKey) -}}
{{- else -}}
{{- include "storefront.registryUrl" .root -}}
{{- end -}}
{{- end }}

{{/*
`storefront.foldedValue`: the scalar `doc` holds under `name`, matched in any
spelling, as a string, or "" when absent.
*/}}
{{- define "storefront.foldedValue" -}}
{{- $key := include "storefront.foldedKey" . -}}
{{- if $key -}}{{- index .doc $key | toString -}}{{- end -}}
{{- end }}

{{/*
Whether `principals` (a list of scheme-tagged identities) includes `principal`.
An entry's `scheme` and `identifier` are matched in any spelling, as the
storefront's loader reads them. Returns "true" or "".
*/}}
{{- define "storefront.includesPrincipal" -}}
{{- $found := false -}}
{{- range $candidate := (.principals | default list) -}}
{{- $scheme := include "storefront.foldedValue" (dict "doc" $candidate "name" "scheme") -}}
{{- $identifier := include "storefront.foldedValue" (dict "doc" $candidate "name" "identifier") -}}
{{- if and (eq $scheme $.principal.scheme) (eq $identifier $.principal.identifier) -}}
{{- $found = true -}}
{{- end -}}
{{- end -}}
{{- if $found -}}true{{- end -}}
{{- end }}

{{/*
Render the per-agent public storefront document, `storefront.json`.

The agent's `config` is the storefront's own configuration and passes through
with its `null` keys removed (`storefront.agents` removes them). The chart
supplies no service default and does not validate the service's settings, which
the storefront does at startup. The chart adds only what the release knows — the
agent's port, its Service URL, the internal registry and provisioning URLs, a
default capacity site, and the database path under the persistence mount — and,
except for the port, only where the configuration does not state it. It refuses
a release whose parts disagree. See openspec/specs/deployment-state/spec.md, "A
storefront chart passes service configuration through".

Keys are matched case-insensitively at every level, as the storefront's loader
matches them, so a check cannot be bypassed by spelling a key differently, and
a configuration stating one key in two spellings is refused. The values schema
accepts every typed field in any spelling too, so no read here may assume one.

Argument: dict with `root` (chart root) and `agent`.
*/}}
{{- define "storefront.agentConfigDocument" -}}
{{- $root := .root -}}
{{- $agent := .agent -}}
{{- $cfg := deepCopy ($agent.config | default dict) -}}
{{- include "storefront.refuseFoldedDuplicates" (dict "agent" $agent.name "path" "config" "value" $cfg) -}}

{{- /* The port names the container port, probes, and Service port. */ -}}
{{- $portKey := include "storefront.foldedKey" (dict "doc" $cfg "name" "port") -}}
{{- if $portKey -}}
  {{- $stated := index $cfg $portKey -}}
  {{- if not (or (kindIs "float64" $stated) (kindIs "int64" $stated) (kindIs "int" $stated)) -}}
    {{- fail (printf "storefront agent %s config.%s must be a number" $agent.name $portKey) -}}
  {{- end -}}
  {{- if ne (float64 $stated) (float64 $agent.port) -}}
    {{- fail (printf "storefront agent %s config.%s %v differs from the agent's port %v" $agent.name $portKey $stated $agent.port) -}}
  {{- end -}}
{{- end -}}
{{- $_ := set $cfg ($portKey | default "port") (int $agent.port) -}}
{{- if not (include "storefront.foldedKey" (dict "doc" $cfg "name" "base_url")) -}}
  {{- $_ := set $cfg "base_url" (include "storefront.agentBaseUrl" .) -}}
{{- end -}}
{{- if not (include "storefront.foldedKey" (dict "doc" $cfg "name" "db_path")) -}}
  {{- $_ := set $cfg "db_path" (printf "%s/agent.db" (trimSuffix "/" $root.Values.persistence.mountPath)) -}}
{{- end -}}

{{- /* Registry: the internal registry's URL, keyed trust stated outside config. */ -}}
{{- $registryKey := include "storefront.foldedKey" (dict "doc" $cfg "name" "registry") | default "registry" -}}
{{- $registry := index $cfg $registryKey | default dict -}}
{{- $trust := $agent.internalRegistryTrust -}}
{{- if include "storefront.foldedKey" (dict "doc" $registry "name" "urls") -}}
  {{- if $trust -}}
    {{- fail (printf "storefront agent %s states internalRegistryTrust and config registry.urls; internalRegistryTrust applies only to the internal registry" $agent.name) -}}
  {{- end -}}
{{- else -}}
  {{- if not $trust -}}
    {{- fail (printf "storefront agent %s uses the internal registry and requires internalRegistryTrust" $agent.name) -}}
  {{- end -}}
  {{- $active := $root.Values.global.registryIdentity -}}
  {{- if ne ($trust.authority | default "") $active.authority -}}
    {{- fail (printf "storefront agent %s internalRegistryTrust.authority %q differs from the release's registry authority %q" $agent.name ($trust.authority | default "") $active.authority) -}}
  {{- end -}}
  {{- if not (include "storefront.includesPrincipal" (dict "principals" $trust.principals "principal" $active.principal)) -}}
    {{- fail (printf "storefront agent %s internalRegistryTrust.principals must include the release's registry principal" $agent.name) -}}
  {{- end -}}
  {{- $url := include "storefront.registryUrl" $root -}}
  {{- $authoritiesKey := include "storefront.foldedKey" (dict "doc" $registry "name" "authorities") | default "authorities" -}}
  {{- $authorities := index $registry $authoritiesKey | default dict -}}
  {{- if include "storefront.foldedKey" (dict "doc" $authorities "name" (lower $url)) -}}
    {{- fail (printf "storefront agent %s states internalRegistryTrust and config registry.authorities[%q]; state one" $agent.name $url) -}}
  {{- end -}}
  {{- $_ := set $authorities $url (dict "authority" $trust.authority "principals" $trust.principals) -}}
  {{- $_ := set $registry $authoritiesKey $authorities -}}
  {{- $_ := set $registry "urls" (list $url) -}}
  {{- $_ := set $cfg $registryKey $registry -}}
{{- end -}}

{{- /* Provisioning and the capacity site bound to it. */ -}}
{{- $internalProvisioningURL := include "provisioning.url" $root -}}
{{- $provisioningKey := include "storefront.foldedKey" (dict "doc" $cfg "name" "provisioning") | default "provisioning" -}}
{{- $provisioning := index $cfg $provisioningKey | default dict -}}
{{- $serviceUrlKey := include "storefront.foldedKey" (dict "doc" $provisioning "name" "service_url") -}}
{{- if not $serviceUrlKey -}}
  {{- $serviceUrlKey = "service_url" -}}
  {{- $_ := set $provisioning $serviceUrlKey $internalProvisioningURL -}}
  {{- $_ := set $cfg $provisioningKey $provisioning -}}
{{- end -}}
{{- $provisioningURL := trimSuffix "/" (toString (index $provisioning $serviceUrlKey)) -}}
{{- $capacityKey := include "storefront.foldedKey" (dict "doc" $cfg "name" "capacity") | default "capacity" -}}
{{- $capacity := index $cfg $capacityKey | default dict -}}
{{- $sitesKey := include "storefront.foldedKey" (dict "doc" $capacity "name" "sites") -}}
{{- if not $sitesKey -}}
  {{- $sitesKey = "sites" -}}
  {{- $_ := set $capacity $sitesKey (dict "default" $provisioningURL) -}}
  {{- $_ := set $cfg $capacityKey $capacity -}}
{{- end -}}

{{- /* Trust in the release's provisioning service is stated, then checked:
every capacity site it serves is verified against that site's service peer,
which must include the release's provisioning principal. */ -}}
{{- if eq $provisioningURL (trimSuffix "/" $internalProvisioningURL) -}}
  {{- $active := $root.Values.global.provisioningIdentity -}}
  {{- $internalSites := list -}}
  {{- range $siteID, $siteURL := (index $capacity $sitesKey) -}}
    {{- if eq (trimSuffix "/" (toString $siteURL)) $provisioningURL -}}
      {{- $internalSites = append $internalSites $siteID -}}
    {{- end -}}
  {{- end -}}
  {{- if $internalSites -}}
    {{- $identity := include "storefront.foldedMap" (dict "doc" $cfg "name" "identity") | fromJson -}}
    {{- $peers := include "storefront.foldedMap" (dict "doc" $identity "name" "service_peers") | fromJson -}}
    {{- $peerTrusted := false -}}
    {{- range $peerID, $peer := $peers -}}
      {{- $role := include "storefront.foldedValue" (dict "doc" $peer "name" "role") -}}
      {{- $siteID := include "storefront.foldedValue" (dict "doc" $peer "name" "site_id") -}}
      {{- $peerPrincipalsKey := include "storefront.foldedKey" (dict "doc" $peer "name" "principals") -}}
      {{- $peerPrincipals := list -}}
      {{- if $peerPrincipalsKey -}}{{- $peerPrincipals = index $peer $peerPrincipalsKey -}}{{- end -}}
      {{- if and (eq $role "service") (has $siteID $internalSites) (include "storefront.includesPrincipal" (dict "principals" $peerPrincipals "principal" $active)) -}}
        {{- $peerTrusted = true -}}
      {{- end -}}
    {{- end -}}
    {{- if not $peerTrusted -}}
      {{- fail (printf "storefront agent %s needs an Identity.service_peers entry with role \"service\" for site %s that includes the release's provisioning principal" $agent.name (join ", " $internalSites)) -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- /* JSON, not YAML: Helm's YAML encoder leaves a string bare unless it
would read back as a 64-bit number, so a 160-bit EVM address such as
0x3c44...93bc is emitted unquoted and a YAML loader reads it as an integer.
JSON quotes every string. */ -}}
{{- toPrettyJson $cfg -}}
{{- end }}

{{/*
Render optional non-identity runtime secrets for local smoke deployments.
Marketplace signer material is never accepted by this helper: the Deployment
reads it directly from identity.credentialSecret.
*/}}
{{- define "storefront.agentSecretsToml" -}}
{{- $agent := .agent -}}
# Rendered by the storefront helm chart (Secret overlay — sensitive only).
# Deep-merged on top of storefront.json at runtime by dynaconf.

{{- if $agent.secret.registryAuthToken }}

[registry.auth]
# Key must match the first registry URL the storefront uses exactly.
{{ include "storefront.effectiveRegistryUrl" . | quote }} = {{ $agent.secret.registryAuthToken | quote }}
{{- end }}
{{- end }}


{{/* Smoke-test profile helpers. Kept local to this subchart because Helm does
not expose root helper templates reliably inside dependency charts. */}}
{{- define "storefront.smokeTestSecretName" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- $secret := $smoke.secret | default dict -}}
{{- if $secret.name -}}
{{- $secret.name -}}
{{- else -}}
{{- printf "%s-test-secret" .Release.Name -}}
{{- end -}}
{{- end }}

{{- define "storefront.smokeTestConfigProfiles" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- $config := $smoke.config | default dict -}}
{{- $profiles := list -}}
{{- if $config.profileFiles -}}
  {{- range $profile := keys $config.profileFiles | sortAlpha -}}
    {{- $profiles = append $profiles $profile -}}
  {{- end -}}
{{- else if $config.profile -}}
  {{- $profiles = append $profiles $config.profile -}}
{{- end -}}
{{- join "," $profiles -}}
{{- end }}

{{- define "storefront.smokeTestSecretProfiles" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- $secret := $smoke.secret | default dict -}}
{{- $internal := $secret.internal | default dict -}}
{{- $external := $secret.external | default dict -}}
{{- $profiles := list -}}
{{- if $secret.enabled -}}
  {{- if and (eq ($secret.type | default "internal") "internal") $internal.profileFiles -}}
    {{- range $profile := keys $internal.profileFiles | sortAlpha -}}
      {{- $profiles = append $profiles $profile -}}
    {{- end -}}
  {{- else if and (eq ($secret.type | default "internal") "external") $external.profileRefs -}}
    {{- range $profile := keys $external.profileRefs | sortAlpha -}}
      {{- $profiles = append $profiles $profile -}}
    {{- end -}}
  {{- else if $secret.profile -}}
    {{- $profiles = append $profiles $secret.profile -}}
  {{- end -}}
{{- end -}}
{{- join "," $profiles -}}
{{- end }}

{{- define "storefront.smokeTestActiveProfiles" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- if $smoke.activeProfiles -}}
{{- $smoke.activeProfiles -}}
{{- else -}}
{{- $profiles := list -}}
{{- $configProfiles := include "storefront.smokeTestConfigProfiles" . -}}
{{- if $configProfiles -}}
  {{- range $profile := splitList "," $configProfiles -}}
    {{- $profiles = append $profiles $profile -}}
  {{- end -}}
{{- end -}}
{{- $secretProfiles := include "storefront.smokeTestSecretProfiles" . -}}
{{- if $secretProfiles -}}
  {{- range $profile := splitList "," $secretProfiles -}}
    {{- $profiles = append $profiles $profile -}}
  {{- end -}}
{{- end -}}
{{- join "," $profiles -}}
{{- end -}}
{{- end }}

{{- define "storefront.smokeTestConfigVolumeMounts" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- $config := $smoke.config | default dict -}}
{{- if $config.profileFiles -}}
{{- range $profile := keys $config.profileFiles | sortAlpha }}
- name: test-config
  mountPath: /app/config/config-{{ $profile }}.yml
  subPath: config-{{ $profile }}.yml
  readOnly: true
{{- end -}}
{{- else if $config.profile }}
- name: test-config
  mountPath: /app/config/config-{{ $config.profile }}.yml
  subPath: config-{{ $config.profile }}.yml
  readOnly: true
{{- end -}}
{{- end }}

{{- define "storefront.smokeTestSecretVolumeMounts" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- $secret := $smoke.secret | default dict -}}
{{- $internal := $secret.internal | default dict -}}
{{- $external := $secret.external | default dict -}}
{{- if $secret.enabled -}}
  {{- if and (eq ($secret.type | default "internal") "internal") $internal.profileFiles -}}
{{- range $profile := keys $internal.profileFiles | sortAlpha }}
- name: test-secret
  mountPath: /app/config/config-{{ $profile }}.yml
  subPath: config-{{ $profile }}.yml
  readOnly: true
{{- end -}}
  {{- else if and (eq ($secret.type | default "internal") "external") $external.profileRefs -}}
{{- range $profile := keys $external.profileRefs | sortAlpha }}
- name: test-secret
  mountPath: /app/config/config-{{ $profile }}.yml
  subPath: config-{{ $profile }}.yml
  readOnly: true
{{- end -}}
  {{- else if $secret.profile }}
- name: test-secret
  mountPath: /app/config/config-{{ $secret.profile }}.yml
  subPath: config-{{ $secret.profile }}.yml
  readOnly: true
  {{- end -}}
{{- end -}}
{{- end }}

{{- define "storefront.smokeTestSecretVolume" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- $secret := $smoke.secret | default dict -}}
{{- if $secret.enabled }}
- name: test-secret
  secret:
    secretName: {{ include "storefront.smokeTestSecretName" . }}
{{- end -}}
{{- end }}
