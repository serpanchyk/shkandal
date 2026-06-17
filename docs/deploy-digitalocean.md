# DigitalOcean Deployment

This is the minimal public-web deployment for Shkandal. It runs only `caddy`,
`frontend`, `backend`, `postgres`, and the one-shot `migrate` job.

## 1. Prepare the server

Create an Ubuntu Droplet, point a firewall at it, and allow inbound `80` and
`443`. Install Docker Engine with the Compose plugin.

Clone the repository onto the server and enter the project directory.

The production deploy script expects the repository at the path configured in
GitHub Actions, currently `/opt/shkandal` on the Droplet.

## 2. Prepare production env files

Copy the tracked examples and fill in real values:

```bash
cp .env.production.example .env.production
cp infra/postgres/.env.production.example infra/postgres/.env.production
```

Set:

- `POSTGRES_DATABASE_URL` to the internal Compose database URL.
- `BACKEND_INTERNAL_URL=http://backend:8000`.
- `PUBLIC_FRONTEND_ORIGIN` and `NEXT_PUBLIC_SITE_URL` to the public origin that
  browsers should use.
- `PUBLIC_HOSTNAME` empty for the first no-domain deployment, or to the final
  hostname later.
- strong PostgreSQL credentials in `infra/postgres/.env.production`.

For a first deployment without a domain, use the server IP in
`PUBLIC_FRONTEND_ORIGIN` and `NEXT_PUBLIC_SITE_URL`, for example
`http://203.0.113.10`, and leave `PUBLIC_HOSTNAME=` empty.

After DNS is ready, set:

```env
PUBLIC_HOSTNAME=example.com
PUBLIC_FRONTEND_ORIGIN=https://example.com
NEXT_PUBLIC_SITE_URL=https://example.com
```

Caddy will then request and renew certificates automatically.

Production env files stay on the Droplet. Do not copy production secrets into
GitHub Actions, commit them to Git, or generate them from CI.

## 3. Build and start the stack

Validate the Compose file:

```bash
docker compose -f docker-compose.prod.yaml --env-file .env.production config
```

Run migrations:

```bash
docker compose -f docker-compose.prod.yaml --env-file .env.production run --rm migrate
```

Start the long-running services:

```bash
docker compose -f docker-compose.prod.yaml --env-file .env.production up -d caddy frontend backend postgres
```

## 4. Verify the deployment

Check service status:

```bash
docker compose -f docker-compose.prod.yaml --env-file .env.production ps
```

Check backend health through Caddy:

```bash
curl http://127.0.0.1/healthz
```

Open the server IP or hostname in a browser. Caddy should route:

- `/api/*` to `backend:8000`
- `/healthz` to `backend:8000`
- everything else to `frontend:3000`

The production deploy script also includes `docker-compose.prod.tunnel.yaml`
when that file is present. This binds Postgres to `127.0.0.1:5432` on the
Droplet only, so local workers can reach production Postgres through an SSH
tunnel without exposing port `5432` publicly.

## 5. Update the deployment

The automated production deployment runs on pushes to `master` and can also be
started manually from the `Deploy Production` GitHub Actions workflow. Configure
these repository variables before enabling it:

- `DROPLET_HOST`: Droplet hostname or IP address.
- `DROPLET_USER`: SSH user that can run Docker Compose in the app directory.
- `DROPLET_APP_DIR`: server repository path, for example `/opt/shkandal`.

Configure this repository secret:

- `DROPLET_SSH_KEY`: private SSH key for that user.

The workflow runs the project checks first, then connects over SSH and runs:

```bash
bash ops/deploy-production
```

For a manual server-side update, run the deploy script from the repository:

```bash
ops/deploy-production
```

The script fetches `origin/master`, resets the server checkout to it, validates
the production Compose file, rebuilds `backend`, `frontend`, and `migrate`, runs
migrations, restarts `caddy`, `frontend`, `backend`, and `postgres`, checks
`/healthz`, and prunes unused Docker images.

## 6. Roll back manually

SSH to the Droplet, enter the app directory, reset to a known good commit, and
rebuild the production services:

```bash
git reset --hard <old_commit>
docker compose -f docker-compose.prod.yaml --env-file .env.production up -d --build
```

## 7. Inspect logs

Follow the public-web service logs:

```bash
docker compose -f docker-compose.prod.yaml --env-file .env.production logs -f caddy backend frontend
```
