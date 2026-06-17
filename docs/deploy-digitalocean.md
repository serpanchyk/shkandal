# DigitalOcean Deployment

This is the minimal public-web deployment for Shkandal. It runs only `caddy`,
`frontend`, `backend`, `postgres`, and the one-shot `migrate` job.

## 1. Prepare the server

Create an Ubuntu Droplet, point a firewall at it, and allow inbound `80` and
`443`. Install Docker Engine with the Compose plugin.

Clone the repository onto the server and enter the project directory.

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

## 5. Update the deployment

Pull the latest code, then rebuild and restart:

```bash
docker compose -f docker-compose.prod.yaml --env-file .env.production build frontend backend migrate
docker compose -f docker-compose.prod.yaml --env-file .env.production run --rm migrate
docker compose -f docker-compose.prod.yaml --env-file .env.production up -d caddy frontend backend postgres
```
