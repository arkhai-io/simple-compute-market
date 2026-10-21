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
`bare-metal-storefront.foldedMap`: the mapping `doc` holds under `name`, as
JSON for fromJson, or {} when absent. JSON keeps every value's type through the
round trip.
*/}}
{{- define "bare-metal-storefront.foldedMap" -}}
{{- $key := include "bare-metal-storefront.foldedKey" . -}}
{{- $value := dict -}}
{{- if $key -}}{{- $value = index .doc $key | default dict -}}{{- end -}}
{{- toJson $value -}}
{{- end -}}

{{/*
`bare-metal-storefront.foldedValue`: the scalar `doc` holds under `name`,
matched in any spelling, as a string, or "" when absent.
*/}}
{{- define "bare-metal-storefront.foldedValue" -}}
{{- $key := include "bare-metal-storefront.foldedKey" . -}}
{{- if $key -}}{{- index .doc $key | toString -}}{{- end -}}
{{- end -}}

{{/*
Whether `principals` (a list of scheme-tagged identities, its keys matched in
any spelling) includes `principal`. Returns "true" or "".
*/}}
{{- define "bare-metal-storefront.includesPrincipal" -}}
{{- $found := false -}}
{{- range $candidate := (.principals | default list) -}}
{{- $scheme := include "bare-metal-storefront.foldedValue" (dict "doc" $candidate "name" "scheme") -}}
{{- $identifier := include "bare-metal-storefront.foldedValue" (dict "doc" $candidate "name" "identifier") -}}
{{- if and (eq $scheme $.principal.scheme) (eq $identifier $.principal.identifier) -}}
{{- $found = true -}}
{{- end -}}
{{- end -}}
{{- if $found -}}true{{- end -}}
{{- end -}}

{{/*
The umbrella release's internal registry URL, when the release has one: the
umbrella's `global.registry` and `global.registryIdentity`. Installed alone, the
chart has neither, and this is "".
*/}}
{{- define "bare-metal-storefront.internalRegistryUrl" -}}
{{- $global := .Values.global | default dict -}}
{{- if and $global.registry $global.registryIdentity -}}
{{- $host := default (printf "%s-registry" .Release.Name) $global.registry.host -}}
{{- printf "http://%s:%d" $host (int $global.registry.port) -}}
{{- end -}}
{{- end -}}

{{/*
The umbrella release's provisioning service URL, when the release has one:
the umbrella's `global.provisioning` and `global.provisioningIdentity`, or "".
*/}}
{{- define "bare-metal-storefront.internalProvisioningUrl" -}}
{{- $global := .Values.global | default dict -}}
{{- if and $global.provisioning $global.provisioningIdentity -}}
{{- printf "http://%s:%d" $global.provisioning.host (int $global.provisioning.port) -}}
{{- end -}}
{{- end -}}

{{/*
A values file's `null` removes what it names, whether or not Helm's merge removed
it: under the supported Helm release, a parent's `null` for a subchart is dropped
only where the subchart's own defaults define the key, and the umbrella or an
overlay supplies `config`'s keys and `internalRegistryTrust`. So the chart reads
both with every `null` removed, and the storefront's document renders as it would
had the removed key never been stated.

`bare-metal-storefront.dropNulls`: remove, in place, every key whose value is `null`
from the mapping `.`, at every depth, inside list elements too; a `null` list
element stays.
*/}}
{{- define "bare-metal-storefront.dropNulls" -}}
{{- if kindIs "map" . -}}
  {{- range $key, $value := . -}}
    {{- if kindIs "invalid" $value -}}
      {{- $_ := unset $ $key -}}
    {{- else -}}
      {{- include "bare-metal-storefront.dropNulls" $value -}}
    {{- end -}}
  {{- end -}}
{{- else if kindIs "slice" . -}}
  {{- range $item := . -}}
    {{- include "bare-metal-storefront.dropNulls" $item -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{/*
Render the public storefront document, `storefront.json`.

`config` is the storefront's own configuration and passes through with its
`null` keys removed. The chart supplies no service default and does not validate
the service's settings, which the storefront does at startup. The chart adds only
what the release knows -- the port its container, probes, and Service share, the
Service's URL, and the database path under the persistence mount; and, in an
umbrella release, its internal registry, with the trust stated as
`internalRegistryTrust` written under its URL, and a `default` site for its
provisioning service -- and, except for the port, only where the configuration
does not state it. In an umbrella release it refuses parts that disagree: trust
that omits the release's registry identity, and a site bound to the release's
provisioning service whose service peer omits its provisioning principal. See
openspec/specs/deployment-state/spec.md, "A storefront chart passes service
configuration through".
*/}}
{{- define "bare-metal-storefront.configDocument" -}}
{{- $cfg := deepCopy (.Values.config | default dict) -}}
{{- include "bare-metal-storefront.dropNulls" $cfg -}}
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

{{- /* Registry: the umbrella's internal registry, its trust stated outside config. */ -}}
{{- $registryKey := include "bare-metal-storefront.foldedKey" (dict "doc" $cfg "name" "registry") | default "registry" -}}
{{- $registry := index $cfg $registryKey | default dict -}}
{{- $trust := deepCopy (.Values.internalRegistryTrust | default dict) -}}
{{- include "bare-metal-storefront.dropNulls" $trust -}}
{{- $internalRegistry := include "bare-metal-storefront.internalRegistryUrl" . -}}
{{- if include "bare-metal-storefront.foldedKey" (dict "doc" $registry "name" "urls") -}}
  {{- if $trust -}}
    {{- fail "bare-metal storefront states internalRegistryTrust and config registry.urls; internalRegistryTrust applies only to the release's internal registry" -}}
  {{- end -}}
{{- else if $internalRegistry -}}
  {{- if not $trust -}}
    {{- fail "bare-metal storefront uses the release's internal registry and requires internalRegistryTrust" -}}
  {{- end -}}
  {{- $active := .Values.global.registryIdentity -}}
  {{- if ne ($trust.authority | default "") $active.authority -}}
    {{- fail (printf "bare-metal storefront internalRegistryTrust.authority %q differs from the release's registry authority %q" ($trust.authority | default "") $active.authority) -}}
  {{- end -}}
  {{- if not (include "bare-metal-storefront.includesPrincipal" (dict "principals" $trust.principals "principal" $active.principal)) -}}
    {{- fail "bare-metal storefront internalRegistryTrust.principals must include the release's registry principal" -}}
  {{- end -}}
  {{- $authoritiesKey := include "bare-metal-storefront.foldedKey" (dict "doc" $registry "name" "authorities") | default "authorities" -}}
  {{- $authorities := index $registry $authoritiesKey | default dict -}}
  {{- if include "bare-metal-storefront.foldedKey" (dict "doc" $authorities "name" (lower $internalRegistry)) -}}
    {{- fail (printf "bare-metal storefront states internalRegistryTrust and config registry.authorities[%q]; state one" $internalRegistry) -}}
  {{- end -}}
  {{- $_ := set $authorities $internalRegistry (dict "authority" $trust.authority "principals" $trust.principals) -}}
  {{- $_ := set $registry $authoritiesKey $authorities -}}
  {{- $_ := set $registry "urls" (list $internalRegistry) -}}
  {{- $_ := set $cfg $registryKey $registry -}}
{{- else if $trust -}}
  {{- fail "bare-metal storefront states internalRegistryTrust, but the release has no internal registry" -}}
{{- end -}}

{{- /* Sites: a `default` site for the umbrella's provisioning service, and every
site bound to it trusted through a service peer naming its principal. */ -}}
{{- $internalProvisioning := include "bare-metal-storefront.internalProvisioningUrl" . -}}
{{- if $internalProvisioning -}}
  {{- $capacityKey := include "bare-metal-storefront.foldedKey" (dict "doc" $cfg "name" "capacity") | default "capacity" -}}
  {{- $capacity := index $cfg $capacityKey | default dict -}}
  {{- $sitesKey := include "bare-metal-storefront.foldedKey" (dict "doc" $capacity "name" "sites") -}}
  {{- if not $sitesKey -}}
    {{- $sitesKey = "sites" -}}
    {{- $_ := set $capacity $sitesKey (dict "default" $internalProvisioning) -}}
    {{- $_ := set $cfg $capacityKey $capacity -}}
  {{- end -}}
  {{- $active := .Values.global.provisioningIdentity -}}
  {{- $identity := include "bare-metal-storefront.foldedMap" (dict "doc" $cfg "name" "identity") | fromJson -}}
  {{- $peers := include "bare-metal-storefront.foldedMap" (dict "doc" $identity "name" "service_peers") | fromJson -}}
  {{- range $siteID, $siteURL := (index $capacity $sitesKey | default dict) -}}
    {{- if eq (trimSuffix "/" (toString $siteURL)) $internalProvisioning -}}
      {{- $trusted := false -}}
      {{- range $peerID, $peer := $peers -}}
        {{- $role := include "bare-metal-storefront.foldedValue" (dict "doc" $peer "name" "role") -}}
        {{- $peerSite := include "bare-metal-storefront.foldedValue" (dict "doc" $peer "name" "site_id") -}}
        {{- $principalsKey := include "bare-metal-storefront.foldedKey" (dict "doc" $peer "name" "principals") -}}
        {{- $principals := list -}}
        {{- if $principalsKey -}}{{- $principals = index $peer $principalsKey -}}{{- end -}}
        {{- if and (eq $role "service") (eq $peerSite $siteID) (include "bare-metal-storefront.includesPrincipal" (dict "principals" $principals "principal" $active)) -}}
          {{- $trusted = true -}}
        {{- end -}}
      {{- end -}}
      {{- if not $trusted -}}
        {{- fail (printf "bare-metal storefront needs an Identity.service_peers entry with role \"service\" for site %s that includes the release's provisioning principal" $siteID) -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- /* JSON, not YAML: Helm's YAML encoder leaves a string bare unless it
would read back as a 64-bit number, so a 160-bit EVM address is emitted
unquoted and a YAML loader reads it as an integer. JSON quotes every string. */ -}}
{{- toPrettyJson $cfg -}}
{{- end -}}
