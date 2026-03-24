# Ghost 6.x CMS for Marketing Agent

Ghost CMS deployment for layer8.schuettken.net — the content hub for the marketing agent pipeline.

## Setup

### Prerequisites
- MariaDB LXC 221 running at 192.168.0.75:3306
- Ghost database and user created:
  ```sql
  CREATE DATABASE ghost_layer8;
  CREATE USER 'ghost'@'%' IDENTIFIED BY 'your-password';
  GRANT ALL PRIVILEGES ON ghost_layer8.* TO 'ghost'@'%';
  FLUSH PRIVILEGES;
  ```
- Cloudflared tunnel configured (domain routing handled by infra)

### Environment Variables
Create `.env` in this directory:
```
GHOST_DB_PASSWORD=<mariadb-ghost-password>
GHOST_ADMIN_API_KEY=<ghost-admin-api-key-from-settings>
```

### Deploy
```bash
docker-compose up -d
```

### First Access
- Web: https://layer8.schuettken.net
- Admin: https://layer8.schuettken.net/ghost
- Set up initial user and theme

### Admin API Key
After initial setup, retrieve the Admin API key from Ghost admin panel:
1. Ghost Admin → Settings → Integrations → Add custom integration
2. Copy the Admin API Key
3. Add to `.env` and restart container

## Health Check
```bash
curl http://localhost:2368/ghost/api/admin/site/
```

## Logs
```bash
docker logs -f marketing-ghost
```

## Storage
Ghost content (posts, media, themes) is persisted in Docker volume `ghost_content`.

To backup:
```bash
docker run --rm -v ghost_content:/data -v $(pwd):/backup alpine tar czf /backup/ghost-backup.tar.gz -C /data .
```

## Notes
- Ghost version: 6.x (Alpine variant — lightweight, suitable for containerization)
- Database: MariaDB 10.5+ (LXC 221)
- Mail: Direct transport (requires outbound SMTP capability on host)
- FastAPI service integration via Admin API (see `../../ghost_client.py`)
