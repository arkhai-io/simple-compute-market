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



{{/* Smoke-test profile helpers. Kept local to this subchart because Helm does
not expose root helper templates reliably inside dependency charts. */}}
{{- define "validate-contracts.smokeTestSecretName" -}}
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

{{- define "validate-contracts.smokeTestConfigProfiles" -}}
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

{{- define "validate-contracts.smokeTestSecretProfiles" -}}
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

{{- define "validate-contracts.smokeTestActiveProfiles" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- if $smoke.activeProfiles -}}
{{- $smoke.activeProfiles -}}
{{- else -}}
{{- $profiles := list -}}
{{- $configProfiles := include "validate-contracts.smokeTestConfigProfiles" . -}}
{{- if $configProfiles -}}
  {{- range $profile := splitList "," $configProfiles -}}
    {{- $profiles = append $profiles $profile -}}
  {{- end -}}
{{- end -}}
{{- $secretProfiles := include "validate-contracts.smokeTestSecretProfiles" . -}}
{{- if $secretProfiles -}}
  {{- range $profile := splitList "," $secretProfiles -}}
    {{- $profiles = append $profiles $profile -}}
  {{- end -}}
{{- end -}}
{{- join "," $profiles -}}
{{- end -}}
{{- end }}

{{- define "validate-contracts.smokeTestConfigVolumeMounts" -}}
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

{{- define "validate-contracts.smokeTestSecretVolumeMounts" -}}
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

{{- define "validate-contracts.smokeTestSecretVolume" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- $secret := $smoke.secret | default dict -}}
{{- if $secret.enabled }}
- name: test-secret
  secret:
    secretName: {{ include "validate-contracts.smokeTestSecretName" . }}
{{- end -}}
{{- end }}
