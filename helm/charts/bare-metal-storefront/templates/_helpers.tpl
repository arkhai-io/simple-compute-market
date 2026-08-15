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
