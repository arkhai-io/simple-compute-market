{{- define "mediation-lane-double.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "mediation-lane-double.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "mediation-lane-double.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
The Service's name. It is not release-scoped: the double's committed leaf
certificate is issued for `mediation-double`, the origin the registry recommends
and every dispute credential names, in Compose lanes and local releases alike.
Two releases in one namespace would both claim it, so a namespace runs one
double.
*/}}
{{- define "mediation-lane-double.serviceName" -}}
mediation-double
{{- end -}}

{{- define "mediation-lane-double.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mediation-lane-double.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "mediation-lane-double.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "mediation-lane-double.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "mediation-lane-double.image" -}}
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
