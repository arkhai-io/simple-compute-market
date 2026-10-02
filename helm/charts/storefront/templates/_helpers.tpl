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
Compose the HTTP RPC URL from global.rpc.host and global.rpc.port.
Mirrors the definition in the root chart's _helpers.tpl.
*/}}
{{- define "rpc.url" -}}
{{- $scheme := .Values.global.rpc.scheme | default "http" -}}
{{- printf "%s://%s:%d" $scheme .Values.global.rpc.host (int .Values.global.rpc.port) -}}
{{- end }}

{{/*
Compose the WebSocket RPC URL from global.rpc.host and global.rpc.port.
Agents connect to Anvil over WebSocket for event subscriptions.
*/}}
{{- define "rpc.wsUrl" -}}
{{- $scheme := ternary "wss" "ws" (eq (.Values.global.rpc.scheme | default "http") "https") -}}
{{- printf "%s://%s:%d" $scheme .Values.global.rpc.host (int .Values.global.rpc.port) -}}
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
Per-agent fullname: {fullname}-{agent.name}.
Used as the Deployment / Service / Secret object name.
Argument: dict with `root` (the chart root) and `agent` (one entry from agents:).
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
The key under which a mapping holds a section, matched case-insensitively as
the storefront's loader matches it, or "" when absent.
Argument: dict with `doc` (a mapping) and `name` (the lowercase section name).
*/}}
{{- define "storefront.sectionKey" -}}
{{- $found := "" -}}
{{- range $key, $_ := .doc -}}
{{- if eq (lower $key) $.name -}}{{- $found = $key -}}{{- end -}}
{{- end -}}
{{- $found -}}
{{- end }}

{{/*
A section of a mapping by case-insensitive name, or an empty dict.
Argument: dict with `doc` and `name`. Returns YAML; read it with fromYaml.
*/}}
{{- define "storefront.section" -}}
{{- $key := include "storefront.sectionKey" . -}}
{{- if $key -}}
{{- toYaml (index .doc $key) -}}
{{- else -}}
{{- toYaml dict -}}
{{- end -}}
{{- end }}

{{/*
Whether the agent uses the release's internal registry: its configuration
names no registry URLs. Returns "true" or "".
*/}}
{{- define "storefront.usesInternalRegistry" -}}
{{- $registry := include "storefront.section" (dict "doc" (.agent.config | default dict) "name" "registry") | fromYaml -}}
{{- if not (hasKey $registry "urls") -}}true{{- end -}}
{{- end }}

{{/*
The first registry URL the agent's storefront uses: the first configured URL,
else the internal registry's.
*/}}
{{- define "storefront.effectiveRegistryUrl" -}}
{{- $registry := include "storefront.section" (dict "doc" (.agent.config | default dict) "name" "registry") | fromYaml -}}
{{- if hasKey $registry "urls" -}}
{{- first $registry.urls -}}
{{- else -}}
{{- include "storefront.registryUrl" .root -}}
{{- end -}}
{{- end }}

{{/*
Whether `principals` (a list of scheme-tagged identities) includes `principal`.
Returns "true" or "".
*/}}
{{- define "storefront.includesPrincipal" -}}
{{- $found := false -}}
{{- range $candidate := (.principals | default list) -}}
{{- if and (eq ($candidate.scheme | default "") $.principal.scheme) (eq ($candidate.identifier | default "") $.principal.identifier) -}}
{{- $found = true -}}
{{- end -}}
{{- end -}}
{{- if $found -}}true{{- end -}}
{{- end }}

{{/*
Render the per-agent public storefront document, `storefront.json`.

The agent's `config` is the storefront's own configuration and passes through
unchanged: the chart supplies no service default and does not validate the
service's settings, which the storefront does at startup. The chart adds only
what the release knows — the agent's port, its Service URL, the internal
registry and provisioning URLs, a default capacity site, and the database path
under the persistence mount — and, except for the port, only where the
configuration does not state it. It refuses a release whose parts disagree.
See openspec/specs/deployment-state/spec.md, "A storefront chart passes
service configuration through".

Section names are matched case-insensitively, as the storefront's loader
matches them, so a check cannot be bypassed by spelling a section differently;
a configuration stating two spellings of one key is refused because the loader
would merge them in an order nobody chose.

Argument: dict with `root` (chart root) and `agent`.
*/}}
{{- define "storefront.agentConfigDocument" -}}
{{- $root := .root -}}
{{- $agent := .agent -}}
{{- $cfg := deepCopy ($agent.config | default dict) -}}
{{- $seen := dict -}}
{{- range $key, $_ := $cfg -}}
  {{- $folded := lower $key -}}
  {{- if hasKey $seen $folded -}}
    {{- fail (printf "storefront agent %s config states both %q and %q; state one" $agent.name (index $seen $folded) $key) -}}
  {{- end -}}
  {{- $_ := set $seen $folded $key -}}
{{- end -}}

{{- /* The port names the container port, probes, and Service port. */ -}}
{{- if and (hasKey $cfg "port") (ne (int (index $cfg "port")) (int $agent.port)) -}}
  {{- fail (printf "storefront agent %s config.port %v differs from the agent's port %v" $agent.name (index $cfg "port") $agent.port) -}}
{{- end -}}
{{- $_ := set $cfg "port" (int $agent.port) -}}
{{- if not (hasKey $cfg "base_url") -}}
  {{- $_ := set $cfg "base_url" (include "storefront.agentBaseUrl" .) -}}
{{- end -}}
{{- if not (hasKey $cfg "db_path") -}}
  {{- $_ := set $cfg "db_path" (printf "%s/agent.db" (trimSuffix "/" $root.Values.persistence.mountPath)) -}}
{{- end -}}

{{- /* Registry: the internal registry's URL, keyed trust stated outside config. */ -}}
{{- $registryKey := include "storefront.sectionKey" (dict "doc" $cfg "name" "registry") | default "registry" -}}
{{- $registry := index $cfg $registryKey | default dict -}}
{{- $trust := $agent.internalRegistryTrust -}}
{{- if hasKey $registry "urls" -}}
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
  {{- $authoritiesKey := include "storefront.sectionKey" (dict "doc" $registry "name" "authorities") | default "authorities" -}}
  {{- $authorities := index $registry $authoritiesKey | default dict -}}
  {{- if hasKey $authorities $url -}}
    {{- fail (printf "storefront agent %s states internalRegistryTrust and config registry.authorities[%q]; state one" $agent.name $url) -}}
  {{- end -}}
  {{- $_ := set $authorities $url (dict "authority" $trust.authority "principals" $trust.principals) -}}
  {{- $_ := set $registry $authoritiesKey $authorities -}}
  {{- $_ := set $registry "urls" (list $url) -}}
  {{- $_ := set $cfg $registryKey $registry -}}
{{- end -}}

{{- /* Provisioning and the capacity site bound to it. */ -}}
{{- $internalProvisioningURL := include "provisioning.url" $root -}}
{{- $provisioningKey := include "storefront.sectionKey" (dict "doc" $cfg "name" "provisioning") | default "provisioning" -}}
{{- $provisioning := index $cfg $provisioningKey | default dict -}}
{{- if not (hasKey $provisioning "service_url") -}}
  {{- $_ := set $provisioning "service_url" $internalProvisioningURL -}}
  {{- $_ := set $cfg $provisioningKey $provisioning -}}
{{- end -}}
{{- $provisioningURL := trimSuffix "/" (toString $provisioning.service_url) -}}
{{- $capacityKey := include "storefront.sectionKey" (dict "doc" $cfg "name" "capacity") | default "capacity" -}}
{{- $capacity := index $cfg $capacityKey | default dict -}}
{{- if not (hasKey $capacity "sites") -}}
  {{- $_ := set $capacity "sites" (dict "default" $provisioningURL) -}}
  {{- $_ := set $cfg $capacityKey $capacity -}}
{{- end -}}

{{- /* Trust in the release's provisioning service is stated, then checked. */ -}}
{{- if eq $provisioningURL (trimSuffix "/" $internalProvisioningURL) -}}
  {{- $active := $root.Values.global.provisioningIdentity -}}
  {{- $provisioningIdentity := include "storefront.section" (dict "doc" $provisioning "name" "identity") | fromYaml -}}
  {{- if not (include "storefront.includesPrincipal" (dict "principals" $provisioningIdentity.principals "principal" $active)) -}}
    {{- fail (printf "storefront agent %s config provisioning.identity.principals must include the release's provisioning principal" $agent.name) -}}
  {{- end -}}
  {{- $internalSites := list -}}
  {{- range $siteID, $siteURL := $capacity.sites -}}
    {{- if eq (trimSuffix "/" (toString $siteURL)) $provisioningURL -}}
      {{- $internalSites = append $internalSites $siteID -}}
    {{- end -}}
  {{- end -}}
  {{- if $internalSites -}}
    {{- $identity := include "storefront.section" (dict "doc" $cfg "name" "identity") | fromYaml -}}
    {{- $peerTrusted := false -}}
    {{- range $peerID, $peer := ($identity.service_peers | default dict) -}}
      {{- if and (eq ($peer.role | default "") "service") (has ($peer.site_id | default "") $internalSites) (include "storefront.includesPrincipal" (dict "principals" $peer.principals "principal" $active)) -}}
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

{{- if $agent.secret.resourcesCsvInline }}
resources_csv_inline = """
{{ $agent.secret.resourcesCsvInline }}
"""
{{- end }}

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
