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
Resolve the Secret name for the SSH private key (default mounted key).
*/}}
{{- define "provisioning.sshKeySecretName" -}}
{{- if .Values.sshKey.secretName -}}
{{- .Values.sshKey.secretName -}}
{{- else -}}
{{- printf "%s-ssh-key" (include "provisioning.fullname" .) -}}
{{- end -}}
{{- end }}

{{/*
Resolve the Secret name for the provisioning-secrets profile file.
This Secret contains config-provisioning-secrets.yml, which is mounted as a
dynaconf profile and carries ssh_decryption_key and inventory_ini.
*/}}
{{- define "provisioning.sshDecryptionKeySecretName" -}}
{{- if .Values.sshDecryptionKey.secretName -}}
{{- .Values.sshDecryptionKey.secretName -}}
{{- else -}}
{{- printf "%s-provisioning-secrets" (include "provisioning.fullname" .) -}}
{{- end -}}
{{- end }}

{{/*
Resolve the ConfigMap name for the production config profile.
*/}}
{{- define "provisioning.configMapName" -}}
{{- printf "%s-config" (include "provisioning.fullname" .) -}}
{{- end }}

{{/*
PVC name backing the provisioning service's SQLite DB. Stable
across releases so reinstalls rebind existing lease state.
*/}}
{{- define "provisioning.pvcName" -}}
{{- printf "%s-data" (include "provisioning.fullname" .) -}}
{{- end }}

{{/*
Compose the registry (indexer) URL from global.registry.host and global.registry.port.
*/}}
{{- define "registry.url" -}}
{{- printf "http://%s:%d" .Values.global.registry.host (int .Values.global.registry.port) -}}
{{- end }}


{{/* Smoke-test profile helpers. Kept local to this subchart because Helm does
not expose root helper templates reliably inside dependency charts. */}}
{{- define "provisioning.smokeTestSecretName" -}}
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

{{- define "provisioning.smokeTestConfigProfiles" -}}
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

{{- define "provisioning.smokeTestSecretProfiles" -}}
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

{{- define "provisioning.smokeTestActiveProfiles" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- if $smoke.activeProfiles -}}
{{- $smoke.activeProfiles -}}
{{- else -}}
{{- $profiles := list -}}
{{- $configProfiles := include "provisioning.smokeTestConfigProfiles" . -}}
{{- if $configProfiles -}}
  {{- range $profile := splitList "," $configProfiles -}}
    {{- $profiles = append $profiles $profile -}}
  {{- end -}}
{{- end -}}
{{- $secretProfiles := include "provisioning.smokeTestSecretProfiles" . -}}
{{- if $secretProfiles -}}
  {{- range $profile := splitList "," $secretProfiles -}}
    {{- $profiles = append $profiles $profile -}}
  {{- end -}}
{{- end -}}
{{- join "," $profiles -}}
{{- end -}}
{{- end }}

{{- define "provisioning.smokeTestConfigVolumeMounts" -}}
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

{{- define "provisioning.smokeTestSecretVolumeMounts" -}}
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

{{- define "provisioning.smokeTestSecretVolume" -}}
{{- $smoke := dict -}}
{{- if .Values.global -}}
  {{- $smoke = .Values.global.smokeTests | default dict -}}
{{- end -}}
{{- $secret := $smoke.secret | default dict -}}
{{- if $secret.enabled }}
- name: test-secret
  secret:
    secretName: {{ include "provisioning.smokeTestSecretName" . }}
{{- end -}}
{{- end }}
