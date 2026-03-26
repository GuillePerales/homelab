# ArgoCD — App of Apps

Patrón App of Apps: una Application raíz que gestiona el resto de Applications.

## Estructura

```
argocd/apps/
├── root-app.yaml          ← Application raíz — apunta a este directorio
├── jenkins.yaml
├── sonarqube.yaml
├── vault.yaml
├── awx.yaml
├── postgresql.yaml
└── cert-manager.yaml
```

## Flujo

```
ArgoCD detecta cambio en Forgejo
    │
    ▼
root-app.yaml sincroniza apps/
    │
    ▼
Cada Application sincroniza su chart/manifiesto
    │
    ▼
K3s actualiza los pods (rolling update)
```

## Convención de Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: nombre-servicio
  namespace: devops
spec:
  project: default
  source:
    repoURL: http://10.0.30.XX:3003/homelab/homelab.git
    targetRevision: main
    path: infrastructure/helm/nombre-servicio
  destination:
    server: https://kubernetes.default.svc
    namespace: namespace-destino
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```
