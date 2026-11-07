{{- define "payments-lane-double.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "payments-lane-double.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "payments-lane-double.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
The Service's name. It is not release-scoped: the double's committed leaf
certificate is issued for `payments-double`, the name every caller dials, in
Compose lanes and local releases alike. Two releases in one namespace would
both claim it, so a namespace runs one double.
*/}}
{{- define "payments-lane-double.serviceName" -}}
payments-double
{{- end -}}

{{- define "payments-lane-double.selectorLabels" -}}
app.kubernetes.io/name: {{ include "payments-lane-double.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "payments-lane-double.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "payments-lane-double.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "payments-lane-double.image" -}}
{{- $repository := .Values.image.repository | default ((.Values.global | default dict).imageRepository | default "") -}}
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
