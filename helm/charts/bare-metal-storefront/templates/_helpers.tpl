{{- define "bare-metal-storefront.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "bare-metal-storefront.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "bare-metal-storefront.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "bare-metal-storefront.selectorLabels" -}}
app.kubernetes.io/name: {{ include "bare-metal-storefront.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: bare-metal-storefront
{{- end -}}

{{- define "bare-metal-storefront.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "bare-metal-storefront.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "bare-metal-storefront.image" -}}
{{- $repository := .Values.image.repository | default .Values.global.imageRepository -}}
{{- $name := .Values.image.name -}}
{{- if $repository -}}
{{- $name = printf "%s/%s" $repository $name -}}
{{- end -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" $name .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" $name .Values.image.tag -}}
{{- end -}}
{{- end -}}

{{- define "bare-metal-storefront.pvcName" -}}
{{- if .Values.persistence.existingClaim -}}
{{- .Values.persistence.existingClaim -}}
{{- else -}}
{{- printf "%s-data" (include "bare-metal-storefront.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "bare-metal-storefront.configMapName" -}}
{{- printf "%s-config" (include "bare-metal-storefront.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
The Service's URL, which the storefront advertises as its base_url unless its
configuration states one.
*/}}
{{- define "bare-metal-storefront.serviceUrl" -}}
{{- printf "http://%s:%d" (include "bare-metal-storefront.fullname" .) (int .Values.port) -}}
{{- end -}}

{{/*
Key lookup as the storefront's loader does it: configuration keys are matched
case-insensitively at every level, so every key the chart reads or writes is
matched the same way; otherwise `Port` would slip past the port check and sit
beside the value the chart writes.

`bare-metal-storefront.foldedKey`: the key under which `doc` holds `name`
(lowercase), in whatever spelling it was written, or "".
*/}}
{{- define "bare-metal-storefront.foldedKey" -}}
{{- $found := "" -}}
{{- range $key, $_ := .doc -}}
{{- if eq (lower $key) $.name -}}{{- $found = $key -}}{{- end -}}
{{- end -}}
{{- $found -}}
{{- end -}}

{{/*
Refuse a mapping, at any depth, that states one key in two spellings: the
loader would merge them in an order nobody chose.
Argument: dict with `path` (dotted, for the message) and `value`.
*/}}
{{- define "bare-metal-storefront.refuseFoldedDuplicates" -}}
{{- $path := .path -}}
{{- if kindIs "map" .value -}}
  {{- $seen := dict -}}
  {{- range $key, $item := .value -}}
    {{- $folded := lower $key -}}
    {{- if hasKey $seen $folded -}}
      {{- fail (printf "bare-metal storefront %s states both %q and %q; state one" $path (index $seen $folded) $key) -}}
    {{- end -}}
    {{- $_ := set $seen $folded $key -}}
    {{- include "bare-metal-storefront.refuseFoldedDuplicates" (dict "path" (printf "%s.%s" $path $key) "value" $item) -}}
  {{- end -}}
{{- else if kindIs "slice" .value -}}
  {{- range $index, $item := .value -}}
    {{- include "bare-metal-storefront.refuseFoldedDuplicates" (dict "path" (printf "%s[%d]" $path $index) "value" $item) -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{/*
Render the public storefront document, `storefront.json`.

`config` is the storefront's own configuration and passes through unchanged:
the chart supplies no service default and does not validate the service's
settings, which the storefront does at startup. The chart adds only what this
release knows -- the port its container, probes, and Service share, the
Service's URL, and the database path under the persistence mount -- and, except
for the port, only where the configuration does not state it. See
openspec/specs/deployment-state/spec.md, "A storefront chart passes service
configuration through".
*/}}
{{- define "bare-metal-storefront.configDocument" -}}
{{- $cfg := deepCopy (.Values.config | default dict) -}}
{{- include "bare-metal-storefront.refuseFoldedDuplicates" (dict "path" "config" "value" $cfg) -}}
{{- $portKey := include "bare-metal-storefront.foldedKey" (dict "doc" $cfg "name" "port") -}}
{{- if $portKey -}}
  {{- $stated := index $cfg $portKey -}}
  {{- if not (or (kindIs "float64" $stated) (kindIs "int64" $stated) (kindIs "int" $stated)) -}}
    {{- fail (printf "bare-metal storefront config.%s must be a number" $portKey) -}}
  {{- end -}}
  {{- if ne (float64 $stated) (float64 .Values.port) -}}
    {{- fail (printf "bare-metal storefront config.%s %v differs from the chart's port %v" $portKey $stated .Values.port) -}}
  {{- end -}}
{{- end -}}
{{- $_ := set $cfg ($portKey | default "port") (int .Values.port) -}}
{{- if not (include "bare-metal-storefront.foldedKey" (dict "doc" $cfg "name" "base_url")) -}}
  {{- $_ := set $cfg "base_url" (include "bare-metal-storefront.serviceUrl" .) -}}
{{- end -}}
{{- if not (include "bare-metal-storefront.foldedKey" (dict "doc" $cfg "name" "db_path")) -}}
  {{- $_ := set $cfg "db_path" (printf "%s/bare-metal-storefront.db" (trimSuffix "/" .Values.persistence.mountPath)) -}}
{{- end -}}
{{- /* JSON, not YAML: Helm's YAML encoder leaves a string bare unless it
would read back as a 64-bit number, so a 160-bit EVM address is emitted
unquoted and a YAML loader reads it as an integer. JSON quotes every string. */ -}}
{{- toPrettyJson $cfg -}}
{{- end -}}
