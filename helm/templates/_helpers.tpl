{{/*
arkhai-node-operator/templates/_helpers.tpl
Shared helpers available to the root chart.
Subcharts define their own _helpers.tpl but may mirror these patterns.
*/}}

{{/*
Expand the name of the root chart.
*/}}
{{- define "arkhai-node-operator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully-qualified app name.
*/}}
{{- define "arkhai-node-operator.fullname" -}}
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

{{/*
Common labels for the root chart.
*/}}
{{- define "arkhai-node-operator.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "arkhai-node-operator.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels for the root chart.
*/}}
{{- define "arkhai-node-operator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "arkhai-node-operator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Resolve a full image reference from a map with keys:
  repository  – subchart-level override (optional)
  name        – image name (required)
  tag         – image tag (required)

Falls back to .Values.global.imageRepository when repository is empty.

Usage:
  image: {{ include "arkhai.image" (dict "imageValues" .Values.image "global" .Values.global) }}
*/}}
{{- define "arkhai.image" -}}
{{- $repo := .imageValues.repository | default .global.imageRepository -}}
{{- if $repo -}}
{{- printf "%s/%s:%s" $repo .imageValues.name .imageValues.tag -}}
{{- else -}}
{{- printf "%s:%s" .imageValues.name .imageValues.tag -}}
{{- end -}}
{{- end }}

{{/*
Compose the RPC URL from global.rpc.host and global.rpc.port.
Defined in the root chart so the pattern is documented centrally.
Each subchart mirrors this with an identical definition in its own _helpers.tpl
because Helm does not make root-chart helpers available inside subcharts.

Usage (inside any chart):
  url: {{ include "arkhai.rpcUrl" . }}
*/}}
{{- define "arkhai.rpcUrl" -}}
{{- printf "http://%s:%d" .Values.global.rpc.host (int .Values.global.rpc.port) -}}
{{- end }}


{{/*
Smoke-test profile helpers. These are intentionally scoped to helm-test pods;
runtime Deployments keep their chart-specific config mechanisms.
*/}}
{{- define "arkhai.smokeTestSecretName" -}}
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

{{- define "arkhai.smokeTestConfigProfiles" -}}
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

{{- define "arkhai.smokeTestSecretProfiles" -}}
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

{{- define "arkhai.smokeTestActiveProfiles" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- if $smoke.activeProfiles -}}
{{- $smoke.activeProfiles -}}
{{- else -}}
{{- $profiles := list -}}
{{- $configProfiles := include "arkhai.smokeTestConfigProfiles" . -}}
{{- if $configProfiles -}}
  {{- range $profile := splitList "," $configProfiles -}}
    {{- $profiles = append $profiles $profile -}}
  {{- end -}}
{{- end -}}
{{- $secretProfiles := include "arkhai.smokeTestSecretProfiles" . -}}
{{- if $secretProfiles -}}
  {{- range $profile := splitList "," $secretProfiles -}}
    {{- $profiles = append $profiles $profile -}}
  {{- end -}}
{{- end -}}
{{- join "," $profiles -}}
{{- end -}}
{{- end }}

{{- define "arkhai.smokeTestConfigVolumeMounts" -}}
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

{{- define "arkhai.smokeTestSecretVolumeMounts" -}}
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

{{- define "arkhai.smokeTestSecretVolume" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- $secret := $smoke.secret | default dict -}}
{{- if $secret.enabled }}
- name: test-secret
  secret:
    secretName: {{ include "arkhai.smokeTestSecretName" . }}
{{- end -}}
{{- end }}

{{/*
A values file's `null` removes what it names, whether or not Helm's merge removed
it, so a storefront agent or the bare-metal storefront's `config` is read here
with every `null` removed, by the rules the storefront charts apply to their own
values; the umbrella cannot include their helpers, since a disabled subchart's
templates are not rendered. See openspec/specs/deployment-state/spec.md, "A
storefront chart passes service configuration through".

`arkhai.dropNulls`: remove, in place, every key whose value is `null` from the
mapping `.`, at every depth, inside list elements too; a `null` list element stays.
*/}}
{{- define "arkhai.dropNulls" -}}
{{- if kindIs "map" . -}}
  {{- range $key, $value := . -}}
    {{- if kindIs "invalid" $value -}}
      {{- $_ := unset $ $key -}}
    {{- else -}}
      {{- include "arkhai.dropNulls" $value -}}
    {{- end -}}
  {{- end -}}
{{- else if kindIs "slice" . -}}
  {{- range $item := . -}}
    {{- include "arkhai.dropNulls" $item -}}
  {{- end -}}
{{- end -}}
{{- end }}

{{/*
`arkhai.storefrontAgents`: the VM storefront's agents with every `null` removed,
set by name into the mapping `into`: a `null` agent is dropped and each other agent
copied without its `null` keys. An agent map naming no agent once they are removed
is refused, as the storefront chart refuses it.
Argument: dict with `root` (the chart root) and `into` (an empty dict).
*/}}
{{- define "arkhai.storefrontAgents" -}}
{{- $into := .into -}}
{{- range $name, $entry := (.root.Values.storefront.agents | default dict) -}}
  {{- if not (kindIs "invalid" $entry) -}}
    {{- $agent := deepCopy $entry -}}
    {{- include "arkhai.dropNulls" $agent -}}
    {{- $_ := set $into $name $agent -}}
  {{- end -}}
{{- end -}}
{{- if not $into -}}
  {{- fail "storefront.agents names no agent once its nulls are removed; a release runs at least one, or sets storefront.enabled false to run none" -}}
{{- end -}}
{{- end }}

{{/*
The key under which a storefront agent's pass-through config mapping `doc`
holds `name` (lowercase), in whatever spelling it was written, or "". The
storefront's loader matches keys case-insensitively, so these reads do too.
*/}}
{{- define "arkhai.storefrontConfigKey" -}}
{{- $found := "" -}}
{{- range $key, $_ := .doc -}}
{{- if eq (lower $key) $.name -}}{{- $found = $key -}}{{- end -}}
{{- end -}}
{{- $found -}}
{{- end }}

{{/*
The scalar a storefront agent's pass-through config mapping `doc` holds under
`name`, matched case-insensitively, as a string, or "" when absent.
*/}}
{{- define "arkhai.storefrontConfigValue" -}}
{{- $key := include "arkhai.storefrontConfigKey" . -}}
{{- if $key -}}{{- index .doc $key | toString -}}{{- end -}}
{{- end }}

{{/*
The mapping a storefront agent's pass-through config mapping `doc` holds under
`name`, matched case-insensitively, as JSON for fromJson, or {} when absent.
*/}}
{{- define "arkhai.storefrontConfigSection" -}}
{{- $key := include "arkhai.storefrontConfigKey" . -}}
{{- $value := dict -}}
{{- if $key -}}{{- $value = index .doc $key | default dict -}}{{- end -}}
{{- toJson $value -}}
{{- end }}
