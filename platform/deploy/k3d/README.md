# Local K3s with k3d

This directory runs the front desk on a local [k3d](https://k3d.io/) cluster. It uses
the same Kubernetes manifests as the production baseline (`deploy/k8s`) with a small
overlay that:

- builds the app image locally as `frontdesk:dev`;
- changes the Ingress host to `localhost`;
- removes the TLS block and the cert-manager annotation, because the local cluster has
  no certificate issuer.

The result is reachable at `http://localhost:8080`.

## Prerequisites

- Docker
- k3d (`k3d --version`)
- kubectl
- Helm 3 (for the CloudNativePG operator)

On Windows, run these commands from a shell where Docker is running. All paths below
are relative to the `platform/` directory.

## 1. Create the cluster

```bash
k3d cluster create --config deploy/k3d/cluster.yaml
kubectl cluster-info
kubectl get nodes
```

The cluster is named `frontdesk` and maps host port `8080` to the cluster load
balancer's port 80. Port `8443` is also mapped for future TLS use. If `8080` is
already taken, edit `deploy/k3d/cluster.yaml`, change the host port, and recreate the
cluster.

Check the name with:

```bash
k3d cluster list
```

## 2. Build and import the image

From `platform/`:

```bash
docker build -t frontdesk:dev .
k3d image import frontdesk:dev -c frontdesk
```

The overlay sets `imagePullPolicy: IfNotPresent`, so the imported image is used
without a registry. Re-run the import after every rebuild.

## 3. Install the CloudNativePG operator

```bash
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm repo update
helm upgrade --install cnpg cnpg/cloudnative-pg \
  --namespace cnpg-system --create-namespace \
  --version 0.29.1
kubectl -n cnpg-system rollout status deploy/cnpg-cloudnative-pg --timeout=300s
```

This is the same operator chart version used by the Flux baseline.

## 4. Create the namespace and application secret

```bash
kubectl apply -f deploy/k8s/namespace.yaml
cp deploy/k8s/secret.example.yaml /tmp/frontdesk-secret.yaml
```

Edit `/tmp/frontdesk-secret.yaml` and fill in:

- Discord bot token, public key, application id, maintainer channel id;
- WhatsApp credentials if you are testing WhatsApp;
- `AI_GATEWAY_API_KEY`, or `LLM_API_KEY` plus `LLM_BASE_URL` in the ConfigMap;
- optional `DISCORD_RESPOND_TO_CHANNEL_IDS`.

Apply it:

```bash
kubectl apply -f /tmp/frontdesk-secret.yaml
```

The app and gateway Deployments also read the CloudNativePG-generated secret
`frontdesk-postgres-app` (key `uri`). Do not create that secret manually.

## 5. Start PostgreSQL first

Apply the database cluster and wait for CloudNativePG to create the application
secret:

```bash
kubectl apply -f deploy/k8s/postgres-cluster.yaml
kubectl -n frontdesk wait \
  --for=condition=Ready cluster/frontdesk-postgres \
  --timeout=300s
kubectl -n frontdesk get secret frontdesk-postgres-app
```

If the cluster does not become ready:

```bash
kubectl -n frontdesk get pods
kubectl -n frontdesk describe cluster frontdesk-postgres
kubectl -n frontdesk logs -l cnpg.io/cluster=frontdesk-postgres
```

The local cluster uses a single PostgreSQL instance with a 10Gi persistent volume
claim. The default k3d storage class is `local-path`; check that it exists with
`kubectl get storageclass`.

## 6. Deploy the app and gateway

```bash
kubectl apply -k deploy/k3d
kubectl -n frontdesk rollout status deploy/frontdesk --timeout=300s
kubectl -n frontdesk rollout status deploy/frontdesk-discord-gateway --timeout=300s
```

The app container runs migrations, seed, and workflow bootstrap on startup because the
baseline sets `RUN_MIGRATIONS`, `RUN_SEED`, and `RUN_WORKFLOW_BOOTSTRAP` to `true`. The
gateway container waits for the app health endpoint before starting its Discord Gateway
connection.

Watch the startup:

```bash
kubectl -n frontdesk get pods
kubectl -n frontdesk logs deploy/frontdesk -f
```

The expected health response:

```bash
curl http://localhost:8080/eve/v1/health
# {"ok":true,"status":"ready","workflowId":"workflow//eve//workflowEntry"}
```

If the Ingress is not routing, port-forward the service directly:

```bash
kubectl -n frontdesk port-forward svc/frontdesk 3000:3000
curl http://localhost:3000/eve/v1/health
```

## 7. Point Discord and WhatsApp at the local app

The app needs a public HTTPS URL for provider webhooks. Expose the local ingress with a
tunnel (Cloudflare Tunnel, ngrok, or similar) and use:

- Discord Interactions Endpoint URL: `https://<tunnel-host>/eve/v1/discord`
- WhatsApp callback URL: `https://<tunnel-host>/eve/v1/whatsapp`

The Discord Gateway listener forwards regular messages internally to
`http://frontdesk:3000/eve/v1/discord`, so it does not need the tunnel. The
`gateway-deployment.yaml` init container waits for the `frontdesk` Service before
starting.

## 8. Rebuild after a code change

```bash
docker build -t frontdesk:dev .
k3d image import frontdesk:dev -c frontdesk
kubectl -n frontdesk rollout restart deploy/frontdesk deploy/frontdesk-discord-gateway
kubectl -n frontdesk rollout status deploy/frontdesk --timeout=300s
```

The imported image replaces the node's cached `frontdesk:dev`; the rollout restart
makes both Deployments pick it up.

## 9. Teardown

```bash
k3d cluster delete frontdesk
docker rmi frontdesk:dev
```

Deleting the cluster removes the local PostgreSQL volume and all conversations. The
`/tmp/frontdesk-secret.yaml` file is outside the repository; delete it when you are
done with it.

## Flux on k3d (optional)

The local overlay is intentionally separate from Flux:

- `deploy/k3d` uses the locally imported `frontdesk:dev` image and strips TLS.
- `deploy/flux` deploys `deploy/k8s`, which references the published registry image
  and expects a real Ingress host and certificate setup.

If you want to exercise Flux locally, install Flux on the k3d cluster, publish the
image to a registry the cluster can pull from, and apply the Flux manifests. Do not
apply `deploy/k3d` and the Flux app Kustomization at the same time; they manage the
same Deployments with different images and ingress settings.
