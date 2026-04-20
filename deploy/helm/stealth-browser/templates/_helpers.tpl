{{/*
Expand the name of the chart.
*/}}
{{- define "stealth-browser.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "stealth-browser.fullname" -}}
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
Create chart name and version as used by the chart label.
*/}}
{{- define "stealth-browser.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "stealth-browser.labels" -}}
helm.sh/chart: {{ include "stealth-browser.chart" . }}
{{ include "stealth-browser.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "stealth-browser.selectorLabels" -}}
app.kubernetes.io/name: {{ include "stealth-browser.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "stealth-browser.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "stealth-browser.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Image name
*/}}
{{- define "stealth-browser.image" -}}
{{- if eq .Values.deploymentMode "all-in-one" }}
{{- printf "%s/%s:%s" .Values.image.registry .Values.image.repository .Values.image.tag }}
{{- else }}
{{- printf "%s/%s-api:%s" .Values.image.registry .Values.image.repository .Values.image.tag }}
{{- end }}
{{- end }}

{{/*
Browser image name
*/}}
{{- define "stealth-browser.browserImage" -}}
{{- printf "%s/%s-browser:%s" .Values.image.registry .Values.image.repository .Values.image.tag }}
{{- end }}
