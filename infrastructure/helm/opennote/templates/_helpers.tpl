{{/*
The release's base name: the release name when it already contains the chart name, else
<release>-opennote. At most 55 characters, so <name>-history still fits a 63-character name.
*/}}
{{- define "opennote.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 55 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 55 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "opennote.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "opennote.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{ include "opennote.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "opennote.tag" -}}
{{- .Values.image.tag | default .Chart.AppVersion -}}
{{- end -}}

{{/* Pod Security "restricted"; no runAsUser, so OpenShift can assign one. */}}
{{- define "opennote.podSecurityContext" -}}
runAsNonRoot: true
{{- if not .Values.openshift.enabled }}
fsGroup: {{ .Values.fsGroup }}
{{- end }}
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "opennote.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end -}}

{{/* The URLs from the existing Secret, for api and worker. */}}
{{- define "opennote.secretEnv" -}}
- name: OPENNOTE_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.existingSecret }}
      key: OPENNOTE_DATABASE_URL
- name: OPENNOTE_VALKEY_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.existingSecret }}
      key: OPENNOTE_VALKEY_URL
{{- end -}}

{{/* api and worker: the two volumes at the paths in the ConfigMap, and /tmp. */}}
{{- define "opennote.backendVolumeMounts" -}}
- name: vaults
  mountPath: /var/lib/opennote/vaults
- name: history
  mountPath: /var/lib/opennote/history
- name: tmp
  mountPath: /tmp
{{- end -}}

{{- define "opennote.backendVolumes" -}}
- name: vaults
  persistentVolumeClaim:
    claimName: {{ include "opennote.fullname" . }}-vaults
- name: history
  persistentVolumeClaim:
    claimName: {{ include "opennote.fullname" . }}-history
- name: tmp
  emptyDir: {}
{{- end -}}
