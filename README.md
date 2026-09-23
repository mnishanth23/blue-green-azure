# Blue-Green Deployments on Azure (AKS + Terraform + Argo Rollouts)

Zero-downtime blue-green releases on Azure Kubernetes Service, built from scratch on a free Azure account. Infrastructure is provisioned with Terraform, and traffic cutover is handled by Argo Rollouts.

> **Status:** work in progress. Infrastructure and a manual blue-green cutover are working. A custom app, load-test evidence, automated analysis and CI/CD are next (see [Roadmap](#roadmap)).

## Architecture

```
                    ┌──────────────────────────── AKS cluster ────────────────────────────┐
                    │                                                                      │
 users ──► Azure LB ──► Service: *-active ────►  ReplicaSet (blue)   ◄── stable / active   │
   (public IP)      │                                                                      │
                    │   Service: *-preview ───►  ReplicaSet (green)  ◄── new release       │
 you ─ port-forward ┘        (internal)                                                    │
                    │                                                                      │
                    │   Argo Rollouts controller ── switches the active Service selector   │
                    │                              from blue to green on promotion         │
                    └──────────────────────────────────────────────────────────────────────┘
                                          │  pulls images (AcrPull via kubelet identity)
                                          ▼
                              Azure Container Registry
```

Both versions run side by side during a release. Production traffic stays on the active version until the new one is verified through the preview Service and explicitly promoted. Promotion swaps the active Service's selector, so the public IP never changes. The old version is kept for a short scale-down delay, which allows an instant rollback.

## Stack

| Layer | Choice |
|---|---|
| Infrastructure as code | Terraform (`azurerm` 4.x) |
| Cluster | AKS, Free control-plane tier, 2 × `Standard_B2s_v2` nodes |
| Networking | Azure CNI Overlay, Standard Load Balancer |
| Registry | Azure Container Registry (Basic), pull access via AcrPull role on the kubelet identity |
| Progressive delivery | Argo Rollouts (`blueGreen` strategy) |

## Repository layout

```
terraform/      AKS, ACR, resource group, AcrPull role assignment
k8s/demo/       Blue-green Rollout using the argoproj/rollouts-demo image
app/            (planned) sample API with /health, /version and a Postgres-backed route
loadtest/       (planned) load script used to prove zero downtime
docs/           (planned) architecture diagram and test evidence
```

## Quick start

**Prerequisites:** Azure CLI, Terraform ≥ 1.6, kubectl (within one minor version of the cluster), and the `kubectl-argo-rollouts` plugin.

### 1. Provision infrastructure

```bash
az login
cd terraform
echo 'subscription_id = "<your-subscription-id>"' > terraform.tfvars   # gitignored

terraform init
terraform plan -out=tfplan
terraform apply tfplan            # ~6 minutes

$(terraform output -raw get_credentials_cmd)
kubectl get nodes
```

### 2. Install Argo Rollouts

```bash
kubectl create namespace argo-rollouts
kubectl apply --server-side --force-conflicts -n argo-rollouts \
  -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml
```

Server-side apply is required: the `rollouts` and `analysisruns` CRDs are too large for the `last-applied-configuration` annotation that a client-side `kubectl apply` writes.

### 3. Run a blue-green release

```bash
kubectl apply -f k8s/demo/rollout.yaml
kubectl get svc rollouts-demo-active          # note the EXTERNAL-IP

# deploy green alongside blue; production traffic stays on blue
kubectl argo rollouts set image rollouts-demo rollouts-demo=argoproj/rollouts-demo:green

# verify green privately
kubectl port-forward svc/rollouts-demo-preview 8081:80

# cut production traffic over to green
kubectl argo rollouts promote rollouts-demo
```

To reject a release instead of promoting it, run `kubectl argo rollouts abort rollouts-demo`. Production stays on the current version and the new pods are discarded.

## Cost control

Running on a free account, so the cluster is only up during working sessions:

```bash
# end of session: remove the cluster, keep the registry and its images
terraform destroy -target=azurerm_kubernetes_cluster.aks

# next session
terraform plan -out=tfplan && terraform apply tfplan
```

The nodes are almost the entire cost. Keeping the Basic ACR between sessions costs very little and preserves its name and images. Use a full `terraform destroy` only when finished with the project.

## Notes from the build

- **VM availability matters as much as quota.** `Standard_B2s` wasn't offered to this subscription in Central India, while `Standard_B2s_v2` was, apart from specific zones. Check with `az vm list-skus -l <region> --size <sku>` before choosing a size.
- **Quota sets the ceiling.** The free subscription allows 4 vCPUs per VM family per region. Two 2-vCPU nodes use all of it, leaving no room for surge nodes during AKS upgrades.
- **Argo Rollouts needs server-side apply**, for the CRD size reason above.

## Roadmap

- [x] Terraform workflow (init → plan → apply → destroy) with local state
- [x] AKS + ACR with AcrPull role assignment
- [x] Argo Rollouts installed; manual blue-green cutover and abort verified on the demo image
- [ ] Custom API (`/health`, `/version`, Postgres-backed route) built and pushed to ACR
- [ ] Load test during promotion, with the status-code log committed as zero-downtime evidence
- [ ] Database changes using the expand/contract pattern
- [ ] Prometheus-backed `AnalysisTemplate` for automatic promotion and rollback
- [ ] Azure Front Door in front of the cluster
- [ ] GitHub Actions pipeline: build → push to ACR → update Rollout image
