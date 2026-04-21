{{- define "provisioning.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "provisioning.fullname" -}}
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

{{- define "provisioning.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "provisioning.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "provisioning.selectorLabels" -}}
app.kubernetes.io/name: {{ include "provisioning.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Resolve the full image reference for the provisioning container.
Supports an optional global.imageRepository passed down from the parent chart.
*/}}
{{- define "provisioning.image" -}}
{{- $repo := .Values.server.image.repository -}}
{{- if and (not $repo) .Values.global -}}
  {{- $repo = .Values.global.imageRepository -}}
{{- end -}}
{{- if $repo -}}
{{- printf "%s/%s:%s" $repo .Values.server.image.name .Values.server.image.tag -}}
{{- else -}}
{{- printf "%s:%s" .Values.server.image.name .Values.server.image.tag -}}
{{- end -}}
{{- end }}

{{/*
Resolve the Secret name for the SSH private key.
*/}}
{{- define "provisioning.sshKeySecretName" -}}
{{- if .Values.sshKey.secretName -}}
{{- .Values.sshKey.secretName -}}
{{- else -}}
{{- printf "%s-ssh-key" (include "provisioning.fullname" .) -}}
{{- end -}}
{{- end }}

{{/*
Resolve the ConfigMap name for the production config profile.
*/}}
{{- define "provisioning.configMapName" -}}
{{- printf "%s-config" (include "provisioning.fullname" .) -}}
{{- end }}

{{/*
Compose the registry (indexer) URL from global.registry.host and global.registry.port.
*/}}
{{- define "registry.url" -}}
{{- printf "http://%s:%d" .Values.global.registry.host (int .Values.global.registry.port) -}}
{{- end }}
