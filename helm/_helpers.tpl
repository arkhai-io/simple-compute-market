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
