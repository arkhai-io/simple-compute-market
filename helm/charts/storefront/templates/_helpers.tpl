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
{{- if $repo -}}
{{- printf "%s/%s:%s" $repo .Values.image.name .Values.image.tag -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.name .Values.image.tag -}}
{{- end -}}
{{- end }}

{{/*
Compose the HTTP RPC URL from global.rpc.host and global.rpc.port.
Mirrors the definition in the root chart's _helpers.tpl.
*/}}
{{- define "rpc.url" -}}
{{- printf "http://%s:%d" .Values.global.rpc.host (int .Values.global.rpc.port) -}}
{{- end }}

{{/*
Compose the WebSocket RPC URL from global.rpc.host and global.rpc.port.
Agents connect to Anvil over WebSocket for event subscriptions.
*/}}
{{- define "rpc.wsUrl" -}}
{{- printf "ws://%s:%d" .Values.global.rpc.host (int .Values.global.rpc.port) -}}
{{- end }}

{{/*
Compose the registry URL from global.registry.host and global.registry.port.
*/}}
{{- define "registry.url" -}}
{{- printf "http://%s:%d" .Values.global.registry.host (int .Values.global.registry.port) -}}
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
Render the per-agent config.toml from values + globals. The output is a
single string the Secret template embeds under `config.toml`.

Argument: dict with `root` (chart root, for global access) and `agent`.

Keys map directly to market_storefront.utils.config.Config field names
(see service.config_loader and storefront/utils/config.py).
*/}}
{{- define "storefront.agentConfigToml" -}}
{{- $root := .root -}}
{{- $agent := .agent -}}
{{- $cfg := $agent.config -}}
{{- $seller := $cfg.seller | default dict -}}
{{- $chain := $cfg.chain | default dict -}}
{{- $prov := $seller.provisioning | default dict -}}
{{- $neg := $seller.negotiation | default dict -}}
# Rendered by the storefront helm chart. Source of truth lives in
# helm/charts/storefront/values.yaml under agents:.

[wallet]
address     = {{ $agent.secret.walletAddress | quote }}
private_key = {{ $agent.secret.privKey | quote }}
ssh_public_key = {{ $seller.sshPublicKey | default "" | quote }}

[chain]
name    = {{ $chain.name | default "ethereum_sepolia" | quote }}
rpc_url = {{ default (include "rpc.wsUrl" $root) $chain.rpcUrl | quote }}
{{- if $chain.alkahestAddressConfigPath }}
alkahest_address_config_path = {{ $chain.alkahestAddressConfigPath | quote }}
{{- end }}

[registry]
url = {{ default (include "registry.url" $root) $cfg.registryUrl | quote }}
identity_registry_address = {{ $root.Values.global.registry.identity_address | quote }}

[seller]
agent_id            = {{ $seller.agentId | quote }}
port                = {{ $agent.port }}
base_url            = {{ $seller.baseUrl | quote }}
db_path             = {{ $seller.dbPath | quote }}
log_file_path       = {{ $seller.logFilePath | quote }}
{{- if $cfg.tokenRegistryPath }}
token_registry_path = {{ $cfg.tokenRegistryPath | quote }}
{{- end }}
enable_event_queue  = {{ $seller.enableEventQueue | default false }}

[seller.provisioning]
service_url = {{ $prov.serviceUrl | default "http://localhost:8085" | quote }}
{{- if $prov.mode }}
mode        = {{ $prov.mode | quote }}
{{- end }}

[seller.negotiation]
policy_mode = {{ $neg.policyMode | default "" | quote }}
{{- end }}
