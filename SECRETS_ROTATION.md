# Secrets Rotation Procedure

## Scheduled Rotation Schedule

| Secret | Rotation Frequency | Procedure |
|---|---|---|
| `INTERNAL_API_KEY` | Every 30 days | Zero-downtime rotation |
| `SECRET_KEY` | Every 90 days | Requires user re-authentication |
| `POSTGRES_PASSWORD` | Every 90 days | Zero-downtime rotation |
| `REDIS_PASSWORD` | Every 90 days | Zero-downtime rotation |
| `ENCRYPTION_KEY` | Every 180 days | Data re-encryption required |

---

## Zero-Downtime Rotation Procedure

### Step 1: Generate new secret
```bash
# Generate cryptographically secure random secret
openssl rand -hex 32
```

### Step 2: Deploy with dual acceptance
1. Update configuration to accept BOTH old and new secrets
2. Deploy to all services
3. Wait 15 minutes for all services to restart

### Step 3: Update clients to use new secret
1. Update all integrations to use the new secret
2. Verify all services are working correctly

### Step 4: Remove old secret
1. Remove old secret from configuration
2. Deploy again
3. Verify no services are using the old secret

---

## Emergency Rotation (Compromise Suspected)

### Execute immediately:
1. Generate ALL new secrets
2. Invalidate all active sessions:
   ```sql
   UPDATE users SET session_version = session_version + 1;
   ```
3. Revoke all API keys:
   ```sql
   UPDATE api_keys SET is_active = false;
   ```
4. Deploy new secrets to all services
5. Notify all users to reset passwords
6. Perform full security audit

---

## Post-Rotation Verification Checklist ✅

- [ ] All services start successfully
- [ ] API endpoints return 200 OK
- [ ] Database connections work
- [ ] Redis connections work
- [ ] Inter-service communication works
- [ ] User authentication works
- [ ] API key authentication works
- [ ] Webhooks are being received
- [ ] No errors in logs
- [ ] Metrics are being collected

---

## Automated Rotation Tools

### HashiCorp Vault:
```bash
# Enable database secrets engine
vault secrets enable database

# Configure PostgreSQL role
vault write database/config/ascenai \
    plugin_name=postgresql-database-plugin \
    connection_url="postgresql://{{username}}:{{password}}@postgres:5432/ascenai" \
    allowed_roles="ascenai-app" \
    username="vault" \
    password="vault-password"

# Create role with 1h TTL
vault write database/roles/ascenai-app \
    db_name=ascenai \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
    default_ttl="1h" \
    max_ttl="24h"
```

### AWS Secrets Manager:
- Enable automatic rotation every 30 days
- Use Lambda function to update database credentials
- Configure rotation without restart

---

## Audit Logging

All secret rotations MUST be logged:
- Date/time of rotation
- Person who performed rotation
- Reason for rotation
- Old secret hash (for audit trail)
- Verification status
```
