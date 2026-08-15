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
Mirrors agentSecretName: honors agent.config.configMapName override,
else auto-generates from the agent fullname.
*/}}
{{- define "storefront.agentConfigMapName" -}}
{{- $cfgName := "" -}}
{{- if .agent.config -}}
{{- $cfgName = .agent.config.configMapName | default "" -}}
{{- end -}}
{{- if $cfgName -}}
{{- $cfgName -}}
{{- else -}}
{{- printf "%s-config" (include "storefront.agentFullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{/*
Render the per-agent non-sensitive storefront.toml. The output is a single
string the ConfigMap template embeds under `storefront.toml`.

Argument: dict with `root` (chart root) and `agent`.

Pairs with an operator-managed storefront.secrets.toml Secret overlay. Public
identity values remain in this ConfigMap; identity credential material is
injected directly from identity.credentialSecret as an environment variable.

Topology-derived values (base_url, registry.urls, and provisioning.service_url)
are composed from the chart's view of the cluster rather than authored as
hardcoded strings in values.yaml.

Anything that isn't here (image, replicas, probes, Service objects,
resources, autoRegister) is k8s-only and never ends up in the agent's
storefront.toml.
*/}}
{{- define "storefront.principalsToml" -}}
{{- $principals := required (printf "%s principals are required" .label) .principals -}}
{{- if or (lt (len $principals) 1) (gt (len $principals) 2) -}}
{{- fail (printf "%s principals must contain one or two identities" .label) -}}
{{- end -}}
principals = [{{ range $i, $principal := $principals }}{{ if $i }}, {{ end }}{ scheme = {{ required (printf "%s principal scheme is required" $.label) $principal.scheme | quote }}, identifier = {{ required (printf "%s principal identifier is required" $.label) $principal.identifier | quote }} }{{ end }}]
{{- end }}

{{- define "storefront.tomlLiteral" -}}
{{- $value := . -}}
{{- if kindIs "map" $value -}}
{ {{- range $index, $key := (keys $value | sortAlpha) }}{{ if $index }}, {{ end }}{{ $key | quote }} = {{ include "storefront.tomlLiteral" (index $value $key) }}{{- end }} }
{{- else if kindIs "slice" $value -}}
[{{- range $index, $item := $value }}{{ if $index }}, {{ end }}{{ include "storefront.tomlLiteral" $item }}{{- end }}]
{{- else if kindIs "string" $value -}}
{{ $value | quote }}
{{- else -}}
{{ $value }}
{{- end -}}
{{- end }}

{{- define "storefront.agentConfigToml" -}}
{{- $root := .root -}}
{{- $agent := .agent -}}
{{- $cfg := $agent.config -}}
{{- $seller := $cfg.seller | default dict -}}
{{- $identity := $agent.identity | default dict -}}
{{- $wallet := $cfg.wallet | default dict -}}
{{- $chains := $cfg.chains | default dict -}}
{{- $prov := $seller.provisioning | default dict -}}
{{- $provIdentity := $prov.identity | default dict -}}
{{- $neg := $seller.negotiation | default dict -}}
{{- $settlement := $cfg.settlement | default dict -}}
{{- $pricing := $cfg.pricing | default dict -}}
{{- $stripe := $settlement.stripe | default dict -}}
{{- $alkahest := $settlement.alkahest | default dict -}}
{{- $registryAuthority := $cfg.registryAuthority | default dict -}}
{{- $domains := required "storefront config.storefrontDomains requires at least one explicit registration" $cfg.storefrontDomains -}}
{{- if lt (len $domains) 1 -}}
  {{- fail "storefront config.storefrontDomains requires at least one explicit registration" -}}
{{- end -}}
{{- if ne (int ($root.Values.image.settlementConfigSchemaVersion | default 0)) (int ($settlement.schema_version | default 0)) -}}
  {{- fail "storefront image and Settlement config schema versions must match" -}}
{{- end -}}
{{- $registryURL := default (include "storefront.registryUrl" $root) $cfg.registryUrl -}}
{{- if not $cfg.registryUrl -}}
  {{- if ne $registryAuthority.authority $root.Values.global.registryIdentity.authority -}}
    {{- fail "storefront registry authority id must match the internal registry authority id" -}}
  {{- end -}}
  {{- $activeRegistryPrincipal := $root.Values.global.registryIdentity.principal -}}
  {{- $activeRegistryTrusted := false -}}
  {{- range $principal := ($registryAuthority.principals | default list) -}}
    {{- if and (eq $principal.scheme $activeRegistryPrincipal.scheme) (eq $principal.identifier $activeRegistryPrincipal.identifier) -}}
      {{- $activeRegistryTrusted = true -}}
    {{- end -}}
  {{- end -}}
  {{- if not $activeRegistryTrusted -}}
    {{- fail "storefront registry authority principals must include the internal registry signer principal" -}}
  {{- end -}}
{{- end -}}
{{- if $prov -}}
  {{- $activeProvisioningPrincipal := $root.Values.global.provisioningIdentity -}}
  {{- $provisioningAuthorityTrusted := false -}}
  {{- range $principal := ($provIdentity.principals | default list) -}}
    {{- if and (eq $principal.scheme $activeProvisioningPrincipal.scheme) (eq $principal.identifier $activeProvisioningPrincipal.identifier) -}}
      {{- $provisioningAuthorityTrusted = true -}}
    {{- end -}}
  {{- end -}}
  {{- if not $provisioningAuthorityTrusted -}}
    {{- fail "provisioning authority principals must include the active provisioning principal" -}}
  {{- end -}}
  {{- $provisioningSiteID := $prov.siteId | default "default" -}}
  {{- $provisioningPeerTrusted := false -}}
  {{- range $peerID, $peer := ($identity.servicePeers | default dict) -}}
    {{- if and (eq ($peer.role | default "") "service") (eq ($peer.siteId | default "") $provisioningSiteID) -}}
      {{- range $principal := ($peer.principals | default list) -}}
        {{- if and (eq $principal.scheme $activeProvisioningPrincipal.scheme) (eq $principal.identifier $activeProvisioningPrincipal.identifier) -}}
          {{- $provisioningPeerTrusted = true -}}
        {{- end -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
  {{- if not $provisioningPeerTrusted -}}
    {{- fail "service-peer trust must include the active provisioning principal for the configured site" -}}
  {{- end -}}
{{- end -}}
{{- $expectedAuthority := $stripe.authority | default dict -}}
{{- if $stripe.enabled -}}
  {{- $conditionProfile := required "enabled Stripe settlement requires condition_profile" $stripe.condition_profile -}}
  {{- if not (hasKey ($stripe.condition_profiles | default dict) $conditionProfile) -}}
    {{- fail "enabled Stripe settlement condition_profile must name a configured condition profile" -}}
  {{- end -}}
  {{- $condition := index $stripe.condition_profiles $conditionProfile -}}
  {{- $evaluator := $condition.evaluator | default dict -}}
  {{- $resolverID := required "enabled Stripe condition profile evaluator requires resolver_id" $evaluator.resolver_id -}}
  {{- if not (hasKey ($stripe.resolvers | default dict) $resolverID) -}}
    {{- fail "enabled Stripe condition profile resolver_id must name a configured resolver" -}}
  {{- end -}}
{{- end -}}
# Rendered by the storefront helm chart (ConfigMap layer — non-sensitive).
# Source of truth lives in helm/charts/storefront/values.yaml under agents:.
# Sensitive values come from the Secret overlay (storefront.secrets.toml).


agent_id            = {{ $seller.agentId | quote }}
port                = {{ $agent.port }}
base_url            = {{ default (include "storefront.agentBaseUrl" .) $seller.baseUrl | quote }}
db_path             = {{ $seller.dbPath | quote }}
log_file_path       = {{ $seller.logFilePath | quote }}
{{- if $seller.resourcesCsvPath }}
resources_csv_path  = {{ $seller.resourcesCsvPath | quote }}
{{- end }}
auto_register       = {{ $agent.autoRegister | default true }}
{{- range $index, $domain := $domains }}

[[storefront_domains]]
contribution = {{ required (printf "storefrontDomains[%d].contribution is required" $index) $domain.contribution | quote }}
offering_mode = {{ required (printf "storefrontDomains[%d].offeringMode is required" $index) $domain.offeringMode | quote }}
domain_identity = {{ required (printf "storefrontDomains[%d].domainIdentity is required" $index) $domain.domainIdentity | quote }}
contract_version = {{ required (printf "storefrontDomains[%d].contractVersion is required" $index) $domain.contractVersion | quote }}
{{- end }}

[Identity.principal]
scheme = {{ required "storefront agent identity.principal.scheme is required" $identity.principal.scheme | quote }}
identifier = {{ required "storefront agent identity.principal.identifier is required" $identity.principal.identifier | quote }}
{{- range $subject, $administrator := ($identity.administrators | default dict) }}

[Identity.administrators.{{ $subject }}]
{{ include "storefront.principalsToml" (dict "label" (printf "identity administrator %s" $subject) "principals" $administrator.principals) }}
{{- end }}
{{- range $peerID, $peer := ($identity.servicePeers | default dict) }}

[Identity.service_peers.{{ $peerID }}]
role = {{ required (printf "identity service peer %s role is required" $peerID) $peer.role | quote }}
site_id = {{ required (printf "identity service peer %s siteId is required" $peerID) $peer.siteId | quote }}
{{ include "storefront.principalsToml" (dict "label" (printf "identity service peer %s" $peerID) "principals" $peer.principals) }}
{{- end }}

{{- if $wallet }}
[Wallet]
{{- if $wallet.address }}
address = {{ $wallet.address | quote }}
{{- end }}
{{- if $wallet.ssh_public_key }}
ssh_public_key = {{ $wallet.ssh_public_key | quote }}
{{- end }}
{{- end }}
{{- range $chainName := keys $chains | sortAlpha }}
{{- $chain := index $chains $chainName }}

[Chains.{{ $chainName }}]
rpc_url = {{ default (include "rpc.wsUrl" $root) $chain.rpc_url | quote }}
chain_id = {{ required (printf "chains.%s.chain_id is required" $chainName) $chain.chain_id | int }}
{{- end }}

[registry]
urls = [{{ $registryURL | quote }}]

[registry.authorities.{{ $registryURL | quote }}]
authority = {{ required "storefront registry authority id is required" $registryAuthority.authority | quote }}
{{ include "storefront.principalsToml" (dict "label" "storefront registry authority" "principals" $registryAuthority.principals) }}
{{- if $agent.rootPath }}

[gateway]
# Gateway path prefix for this agent. Used by FastAPI's custom OpenAPI
# function to inject a servers block so Swagger UI generates correct
# curl examples when accessed through the API gateway. Empty for local dev.
root_path = {{ $agent.rootPath | quote }}
{{- end }}

[provisioning]
service_url = {{ default (include "provisioning.url" $root) $prov.serviceUrl | quote }}
{{- if $prov.mode }}
mode        = {{ $prov.mode | quote }}
{{- end }}
{{- if $prov.pollInterval }}
poll_interval = {{ $prov.pollInterval | int }}
{{- end }}

[provisioning.identity]
{{ include "storefront.principalsToml" (dict "label" "provisioning identity" "principals" $provIdentity.principals) }}

{{- if $pricing }}
[pricing]
{{- if hasKey $pricing "default_min_price" }}
default_min_price = {{ include "storefront.tomlLiteral" $pricing.default_min_price }}
{{- end }}
{{- if hasKey $pricing "default_token_address" }}
default_token_address = {{ include "storefront.tomlLiteral" $pricing.default_token_address }}
{{- end }}
{{- if hasKey $pricing "default_max_duration_seconds" }}
default_max_duration_seconds = {{ $pricing.default_max_duration_seconds | int }}
{{- end }}
settlements = {{ include "storefront.tomlLiteral" $pricing.settlements }}
{{- end }}

[Settlement]
schema_version = {{ $settlement.schema_version | default 1 }}
priority = [{{ range $i, $mechanism := ($settlement.priority | default list) }}{{ if $i }}, {{ end }}{{ $mechanism | quote }}{{ end }}]

{{- if $stripe }}
[Settlement.stripe]
enabled = {{ $stripe.enabled | default false }}
{{- if $stripe.base_url }}
base_url = {{ $stripe.base_url | quote }}
{{- end }}
{{- if $stripe.authority_id }}
authority_id = {{ $stripe.authority_id | quote }}
{{- end }}
{{- if $stripe.environment }}
environment = {{ $stripe.environment | quote }}
{{- end }}
{{- if $stripe.expected_manifest_digest }}
expected_manifest_digest = {{ $stripe.expected_manifest_digest | quote }}
{{- end }}
expected_api_version = {{ $stripe.expected_api_version | default "0.2.1" | quote }}
expected_schema_version = {{ $stripe.expected_schema_version | default 5 }}
required_capabilities = [{{ range $i, $cap := ($stripe.required_capabilities | default list) }}{{ if $i }}, {{ end }}{{ $cap | quote }}{{ end }}]
{{- if $stripe.account_ref }}
account_ref = {{ $stripe.account_ref | quote }}
{{- end }}
currency = {{ $stripe.currency | default "usd" | quote }}
country = {{ $stripe.country | default "US" | quote }}
{{- if $stripe.condition_profile }}
condition_profile = {{ $stripe.condition_profile | quote }}
{{- end }}
request_timeout_seconds = {{ $stripe.request_timeout_seconds | default 10.0 }}
preflight_timeout_seconds = {{ $stripe.preflight_timeout_seconds | default 5.0 }}
allow_insecure_loopback = {{ $stripe.allow_insecure_loopback | default false }}
{{- if $expectedAuthority.principals }}

[Settlement.stripe.authority]
{{ include "storefront.principalsToml" (dict "label" "Stripe settlement authority" "principals" $expectedAuthority.principals) }}
{{- end }}
{{- range $profileID, $profile := ($stripe.condition_profiles | default dict) }}

[Settlement.stripe.condition_profiles.{{ $profileID | quote }}]
{{ range $field := keys $profile | sortAlpha }}
{{ $field }} = {{ include "storefront.tomlLiteral" (index $profile $field) }}
{{ end }}
{{- end }}
{{- range $resolverID, $resolver := ($stripe.resolvers | default dict) }}

[Settlement.stripe.resolvers.{{ $resolverID | quote }}]
chain_name = {{ $resolver.chain_name | quote }}
evidence_mode = {{ $resolver.evidence_mode | quote }}
{{- end }}
{{- end }}

{{- if $alkahest }}
[Settlement.alkahest]
enabled = {{ $alkahest.enabled | default false }}
{{- if $alkahest.address_config_path }}
address_config_path = {{ $alkahest.address_config_path | quote }}
{{- end }}
oracle_gated = {{ $alkahest.oracle_gated | default false }}
trusted_oracle_addresses = [{{ range $i, $address := ($alkahest.trusted_oracle_addresses | default list) }}{{ if $i }}, {{ end }}{{ $address | quote }}{{ end }}]
interruptible = {{ $alkahest.interruptible | default false }}
interruptible_oracle_addresses = [{{ range $i, $address := ($alkahest.interruptible_oracle_addresses | default list) }}{{ if $i }}, {{ end }}{{ $address | quote }}{{ end }}]
{{- end }}

[negotiation]
{{- if $neg.policies }}
policies = [{{ range $i, $mw := $neg.policies }}{{ if $i }}, {{ end }}{{ $mw | quote }}{{ end }}]
{{- else if $neg.policyMode }}
policy_mode = {{ $neg.policyMode | quote }}
{{- end }}
{{- end }}

{{/*
Render optional non-identity runtime secrets for local smoke deployments.
Marketplace signer material is never accepted by this helper: the Deployment
reads it directly from identity.credentialSecret.
*/}}
{{- define "storefront.agentSecretsToml" -}}
{{- $root := .root -}}
{{- $agent := .agent -}}
{{- $cfg := $agent.config -}}
{{- $seller := $cfg.seller | default dict -}}
{{- $integ := $seller.integrations | default dict -}}
# Rendered by the storefront helm chart (Secret overlay — sensitive only).
# Deep-merged on top of storefront.toml at runtime by dynaconf.

{{- if $agent.secret.resourcesCsvInline }}
resources_csv_inline = """
{{ $agent.secret.resourcesCsvInline }}
"""
{{- end }}

{{- if $agent.secret.registryAuthToken }}

[registry.auth]
# Key must match the rendered [registry] urls entry exactly.
{{ default (include "storefront.registryUrl" $root) ($cfg.registryUrl) | quote }} = {{ $agent.secret.registryAuthToken | quote }}
{{- end }}
{{- if or $integ.geminiApiKey $integ.gemini_api_key }}

[integrations]
gemini_api_key = {{ default $integ.geminiApiKey $integ.gemini_api_key | quote }}
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
