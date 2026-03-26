# K8s — Apps personalizadas

Manifiestos para workloads propios que no tienen chart Helm o necesitan configuración custom.

## Estructura planificada

```
apps/
├── placeholder-app/        ← App de ejemplo para validar el pipeline end-to-end
│   ├── deployment.yaml
│   ├── service.yaml
│   └── ingress.yaml
├── postgresql-backup/      ← CronJob pg_dump → tank/backups/databases/
│   └── cronjob.yaml
├── k3s-backup/             ← CronJob backup SQLite K3s state.db
│   └── cronjob.yaml
└── awx/                    ← AWX Custom Resource (AWX Operator)
    └── awx.yaml
```

## placeholder-app

Aplicación mínima (nginx sirviendo una página estática) para:
- Validar el pipeline completo Jenkins → Harbor → ArgoCD → K3s
- Demostrar rolling updates declarativos
- Servir de plantilla para aplicaciones reales
