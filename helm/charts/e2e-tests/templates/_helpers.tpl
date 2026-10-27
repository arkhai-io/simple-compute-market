{{/*
charts/e2e-tests/templates/_helpers.tpl
*/}}

{{- define "e2e-tests.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "e2e-tests.fullname" -}}
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

{{- define "e2e-tests.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "e2e-tests.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "e2e-tests.selectorLabels" -}}
app.kubernetes.io/name: {{ include "e2e-tests.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Labels for this chart's Helm test pod. Every workload selector in the release
requires app.kubernetes.io/name, so a test pod carries the release's other
labels but never that one: selecting a workload's pods by its selector, as
`kubectl logs -l` or `kubectl logs deploy/...` does, never returns a test pod.
*/}}
{{- define "e2e-tests.testLabels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: test
{{- end }}

{{/*
Resolve the integration test image. Prefers .Values.integrationTests.repository,
falls back to global.imageRepository, then bare image name.
*/}}
{{- define "e2e-tests.image" -}}
{{- $repo := .Values.integrationTests.repository -}}
{{- if and (not $repo) .Values.global -}}
  {{- $repo = .Values.global.imageRepository | default "" -}}
{{- end -}}
{{- $name := .Values.integrationTests.name -}}
{{- if $repo -}}
  {{- $name = printf "%s/%s" $repo $name -}}
{{- end -}}
{{- if .Values.integrationTests.digest -}}
{{- printf "%s@%s" $name .Values.integrationTests.digest -}}
{{- else -}}
{{- printf "%s:%s" $name .Values.integrationTests.tag -}}
{{- end -}}
{{- end }}

{{/*
Name of the e2e credentials Secret.
*/}}
{{- define "e2e-tests.secretName" -}}
{{- required "e2e-tests.secretName must reference a pre-existing Secret" .Values.secretName -}}
{{- end }}
