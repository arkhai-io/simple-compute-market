{{/*
charts/validate-contracts/templates/_helpers.tpl
*/}}

{{- define "validate-contracts.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "validate-contracts.fullname" -}}
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

{{- define "validate-contracts.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "validate-contracts.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "validate-contracts.selectorLabels" -}}
app.kubernetes.io/name: {{ include "validate-contracts.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Resolve the RPC URL for the contract validation test.
Uses .Values.rpcUrl when set; otherwise composes the URL from
global.rpc.host and global.rpc.port, which resolves to the test-env
service when that subchart is enabled.
*/}}
{{- define "validate-contracts.rpcUrl" -}}
{{- if .Values.rpcUrl -}}
{{- .Values.rpcUrl -}}
{{- else -}}
{{- printf "http://%s:%d" .Values.global.rpc.host (int .Values.global.rpc.port) -}}
{{- end -}}
{{- end }}
