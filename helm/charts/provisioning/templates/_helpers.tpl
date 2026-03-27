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
Resolve the full image reference for the API server container.
Supports an optional global.imageRepository passed down from the parent.
*/}}
{{- define "provisioning.apiImage" -}}
{{- $repo := .Values.apiServer.image.repository -}}
{{- if and (not $repo) .Values.global -}}
  {{- $repo = .Values.global.imageRepository -}}
{{- end -}}
{{- if $repo -}}
{{- printf "%s/%s:%s" $repo .Values.apiServer.image.name .Values.apiServer.image.tag -}}
{{- else -}}
{{- printf "%s:%s" .Values.apiServer.image.name .Values.apiServer.image.tag -}}
{{- end -}}
{{- end }}

{{/*
Resolve the full image reference for the worker container.
*/}}
{{- define "provisioning.workerImage" -}}
{{- $repo := .Values.worker.image.repository -}}
{{- if and (not $repo) .Values.global -}}
  {{- $repo = .Values.global.imageRepository -}}
{{- end -}}
{{- if $repo -}}
{{- printf "%s/%s:%s" $repo .Values.worker.image.name .Values.worker.image.tag -}}
{{- else -}}
{{- printf "%s:%s" .Values.worker.image.name .Values.worker.image.tag -}}
{{- end -}}
{{- end }}

{{/*
Compose the registry (indexer) URL from global.registry.host and global.registry.port.
*/}}
{{- define "registry.url" -}}
{{- printf "http://%s:%d" .Values.global.registry.host (int .Values.global.registry.port) -}}
{{- end }}

{{/*
Compose the internal Redis URL for the provisioning service.
*/}}
{{- define "provisioning.redisUrl" -}}
{{- printf "redis://%s-redis:%d/0" (include "provisioning.fullname" .) (int .Values.redis.port) -}}
{{- end }}

{{/*
Common environment variables shared by both the API server and worker containers.
*/}}
{{- define "provisioning.commonEnv" -}}
# --- sourced from subchart values ---
- name: LOG_LEVEL
  value: {{ .Values.config.logLevel | quote }}
- name: DATABASE_URL
  value: {{ .Values.config.databaseUrl | quote }}
- name: REDIS_QUEUE_NAME
  value: {{ .Values.config.redisQueueName | quote }}
- name: ANSIBLE_TIMEOUT_SECONDS
  value: {{ .Values.config.ansibleTimeoutSeconds | quote }}
- name: DEFAULT_VM_HOST
  value: {{ .Values.config.defaultVmHost | quote }}
- name: ZEROTIER_NETWORK
  value: {{ .Values.config.zerotierNetwork | quote }}
- name: ENABLE_AUTH
  value: {{ .Values.config.enableAuth | quote }}
- name: REGISTRY_CACHE_TTL_SECONDS
  value: {{ .Values.config.registryCacheTtlSeconds | quote }}
- name: REGISTRY_CACHE_MAX_SIZE
  value: {{ .Values.config.registryCacheMaxSize | quote }}
- name: ENABLE_RATE_LIMITING
  value: {{ .Values.config.enableRateLimiting | quote }}
- name: RATE_LIMIT_REQUESTS_PER_MINUTE
  value: {{ .Values.config.rateLimitRequestsPerMinute | quote }}
# --- sourced from global ---
- name: REGISTRY_URL
  value: {{ include "registry.url" . | quote }}
# --- sourced from helpers ---
- name: REDIS_URL
  value: {{ include "provisioning.redisUrl" . | quote }}
{{- end }}

{{/*
Init container that waits for Redis before either main container starts.
*/}}
{{- define "provisioning.waitForRedis" -}}
- name: wait-for-redis
  image: redis:7-alpine
  command:
    - sh
    - -c
    - |
      echo "Waiting for Redis at {{ include "provisioning.fullname" . }}-redis:{{ .Values.redis.port }}..."
      until redis-cli -h {{ include "provisioning.fullname" . }}-redis -p {{ .Values.redis.port }} ping 2>&1 | grep -q PONG; do
        echo "Redis not ready, retrying in 3s..."; sleep 3
      done
      echo "Redis ready."
{{- end }}
