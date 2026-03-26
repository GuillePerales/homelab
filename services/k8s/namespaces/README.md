# K8s — Namespaces, RBAC y NetworkPolicies

Manifiestos de infraestructura K8s: namespaces, ServiceAccounts, Roles y NetworkPolicies.

## Namespaces

| Namespace | Workloads | NetworkPolicy |
|---|---|---|
| `devops` | Jenkins, ArgoCD, SonarQube | default-deny + excepciones explícitas |
| `vault` | HashiCorp Vault | default-deny + excepciones mínimas |
| `database` | PostgreSQL | default-deny + acceso solo desde devops/awx |
| `awx` | AWX + Operator | default-deny + salida a inventario Ansible |
| `monitoring` | Prometheus, Grafana (si se migra a K3s) | default-deny |
| `apps` | placeholder-app y futuras apps propias | default-deny |

## Estructura planificada

```
namespaces/
├── devops/
│   ├── namespace.yaml
│   ├── network-policy.yaml    ← default-deny + excepciones
│   └── rbac.yaml              ← ServiceAccounts + Roles
├── vault/
│   ├── namespace.yaml
│   └── network-policy.yaml
├── database/
│   ├── namespace.yaml
│   └── network-policy.yaml
├── awx/
│   ├── namespace.yaml
│   └── network-policy.yaml
└── apps/
    ├── namespace.yaml
    └── network-policy.yaml
```

## Patrón NetworkPolicy default-deny

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: NAMESPACE
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```

Excepciones se añaden como políticas adicionales con `podSelector` específico.
