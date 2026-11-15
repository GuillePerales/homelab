# ArgoCD — App of Apps

Patrón App of Apps: una Application raíz que gestiona el resto de Applications.

## Estructura

```
argocd/apps/
├── root-app.yaml          ← Application raíz: lo único que se aplica a mano
├── cert-manager.yaml      ← chart + ClusterIssuer (services/k8s/apps/cert-manager)
├── platform.yaml          ← NetworkPolicies de argocd, cert-manager y vault (services/k8s/platform)
├── envs.yaml              ← namespaces dev y prod, con cuota y aislamiento (services/k8s/envs)
├── homelab-check-dev.yaml ← sigue main
└── homelab-check-prod.yaml← sigue la etiqueta de versión más alta (semver)
```

Cada servicio nuevo es un fichero más en este directorio. Dev recibe cada cambio fusionado en main; prod, solo cuando se etiqueta una versión (`git tag vX.Y.Z`). Los secretos de cada entorno viven en Vault (`homelab/dev/*` y `homelab/prod/*`), configurados con `infrastructure/scripts/vault-k8s-envs/setup.sh`. Jenkins, SonarQube, AWX y
PostgreSQL no se despliegan en el clúster (alcance de la fase 4b).

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
