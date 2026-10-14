{{/* Имя релиза служит префиксом всех объектов: alpha, alpha-worker, alpha-postgres, ... */}}
{{- define "alpha.fullname" -}}
{{- .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}

{{- define "alpha.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Селектор компонента: include "alpha.selector" (list . "server") */}}
{{- define "alpha.selector" -}}
{{- $root := index . 0 -}}
app.kubernetes.io/name: {{ $root.Chart.Name }}
app.kubernetes.io/instance: {{ $root.Release.Name }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end -}}

{{- define "alpha.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end -}}

{{/*
Окружение server и worker: ConfigMap, все ключи секрета, и DATABASE_URL,
собранный из пароля, если Postgres ставится этим же чартом.
*/}}
{{- define "alpha.appEnv" -}}
envFrom:
  - configMapRef:
      name: {{ include "alpha.fullname" . }}-config
  - secretRef:
      name: {{ .Values.existingSecret }}
{{- if .Values.postgres.enabled }}
env:
  - name: POSTGRES_PASSWORD
    valueFrom:
      secretKeyRef: { name: {{ .Values.existingSecret }}, key: POSTGRES_PASSWORD }
  - name: DATABASE_URL
    value: "postgres://{{ .Values.postgres.user }}:$(POSTGRES_PASSWORD)@{{ include "alpha.fullname" . }}-postgres:5432/{{ .Values.postgres.database }}?sslmode=disable"
{{- end }}
{{- end -}}
