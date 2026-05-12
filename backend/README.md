# Profits Check Backend

Backend service for portfolio statistics and snapshots.

## Security Configuration

Required environment variables:

- `APP_ENCRYPTION_KEY`: Fernet key used to encrypt exchange secrets at rest.
- `PROFITS_CHECK_BOOTSTRAP_PASSWORD`: initial single-user admin password. It is only needed until the first successful startup creates the stored password hash.

Optional environment variables:

- `PROFITS_CHECK_COOKIE_SECURE=true`: mark the session cookie as Secure when an HTTPS reverse proxy is in front of the app.
- `PROFITS_CHECK_ALLOW_CUSTOM_PROVIDER_URLS=true`: development-only escape hatch for custom exchange/RPC URLs.

Generate a Fernet key with:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```
