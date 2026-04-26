# Production Secrets Management Guide

## Critical Security Requirements

### ❌ NEVER DO THESE THINGS:
1. Never commit secrets to version control
2. Never use the default `.env` file in production
3. Never use weak or short secret values
4. Never reuse secrets across environments
5. Never hardcode secrets in configuration files

---

## Required Secrets for Production

| Secret | Purpose | Required Length | Generation Command | Rotation Frequency |
|---|---|---|---|---|
| `SECRET_KEY` | JWT signing, session encryption | ≥32 chars | `openssl rand -hex 32` | 90 days |
| `INTERNAL_API_KEY` | Inter-service authentication | ≥32 chars | `openssl rand -hex 32` | 30 days |
| `ENCRYPTION_KEY` | Sensitive data encryption at rest | 32 bytes (base64) | `openssl rand -base64 32` | 180 days |
| `POSTGRES_PASSWORD` | Database credentials | ≥16 chars | `openssl rand -hex 16` | 90 days |
| `REDIS_PASSWORD` | Redis credentials | ≥16 chars | `openssl rand -hex 16` | 90 days |

---

## Secrets Manager Integration

### Recommended Solutions:

| Provider | Integration Notes |
|---|---|
| **HashiCorp Vault** | Full enterprise solution with dynamic secrets and rotation |
| **AWS Secrets Manager** | Native AWS integration with automatic rotation |
| **GCP Secret Manager** | Native GCP integration |
| **Azure Key Vault** | Native Azure integration |
| **Doppler** | Developer-friendly secrets management |

### Integration Pattern:

1. Remove all secrets from `.env` file
2. Configure your secrets manager as the single source of truth
3. Inject secrets at runtime via environment variables
4. Never mount secrets as files in containers
5. Use short-lived credentials for database access

---

## Production Hardening Steps

### 1. Remove Secrets from `.env`
```bash
# Production .env should ONLY contain non-sensitive config:
ENVIRONMENT=production
LLM_PROVIDER=gemini
DOMAIN=yourdomain.com
FRONTEND_URL=https://app.yourdomain.com

# ALL SECRETS MUST COME FROM SECRETS MANAGER
```

### 2. Docker Secrets (Swarm Mode)
```yaml
secrets:
  postgres_password:
    external: true
  redis_password:
    external: true
  secret_key:
    external: true
```

### 3. Kubernetes Secrets
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ascenai-secrets
type: Opaque
stringData:
  SECRET_KEY: "your-secret-key"
  POSTGRES_PASSWORD: "your-db-password"
```

---

## Rotation Procedures

### Emergency Rotation (Compromise Suspected):
1. Generate new secrets immediately
2. Invalidate all existing sessions:
   ```bash
   # Increment session version for all users
   UPDATE users SET session_version = session_version + 1;
   ```
3. Restart all services
4. Revoke all API keys

### Scheduled Rotation:
1. Generate new secret value
2. Deploy with both old and new secrets temporarily
3. Update all services to use new secret
4. Remove old secret after transition period
5. Verify all systems are working

---

## Audit Checklist ✅

- [ ] All secrets are ≥32 characters
- [ ] No default/weak secrets in use
- [ ] Secrets are rotated on schedule
- [ ] Secrets are not logged anywhere
- [ ] Secrets are not visible in process lists
- [ ] Secrets are not included in backups
- [ ] Access to secrets is restricted on need-to-know basis
- [ ] All secret changes are audited

---

## Security Best Practices

1. **Principle of Least Privilege**: Each service gets only the secrets it needs
2. **Short-lived Credentials**: Use dynamic database credentials where possible
3. **Audit Logging**: Log all secret access events
4. **Encryption at Rest**: All secrets stored encrypted
5. **Encryption in Transit**: Secrets never transmitted over unencrypted channels
