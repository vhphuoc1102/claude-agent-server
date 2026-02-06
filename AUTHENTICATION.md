# API Key Authentication Guide

## Overview

The Claude SDK Server now supports API key authentication using Bearer tokens. All endpoints except `/` and `/health` require authentication.

## Quick Start

### 1. Generate an API Key

```bash
# Using OpenSSL (recommended)
openssl rand -hex 32

# Using Python
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Example output: `8accaWTG5s3QvRHrV1y7IQ5Bo5g2OifX898Qm5iyg14`

### 2. Configure the Server

Add the API key to your `.env` file:

```env
API_KEY=your_generated_key_here
```

### 3. Start the Server

```bash
python server.py
```

You should see:
```
🔒 API authentication enabled
INFO:     Started server process...
```

If `API_KEY` is not set, you'll see:
```
⚠️  API_KEY not set - authentication disabled (development only)
```

## Using the API

### Authentication Header Format

All protected endpoints require the `Authorization` header with a Bearer token:

```
Authorization: Bearer YOUR_API_KEY
```

### Example Requests

#### Using curl

```bash
# Set your API key
export API_KEY="your_api_key_here"

# Test a protected endpoint
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"prompt": "Hello Claude!", "allowed_tools": []}'
```

#### Using Python

```python
import requests

API_KEY = "your_api_key_here"
headers = {"Authorization": f"Bearer {API_KEY}"}

response = requests.post(
    "http://localhost:8000/query",
    headers=headers,
    json={
        "prompt": "Hello Claude!",
        "allowed_tools": []
    }
)

print(response.json())
```

#### Using httpie

```bash
http POST localhost:8000/query \
  Authorization:"Bearer your_api_key_here" \
  prompt="Hello Claude!" \
  allowed_tools:=[]
```

## Protected Endpoints

The following endpoints require authentication:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/skills` | GET | List available skills |
| `/query` | POST | One-shot query |
| `/query/stream` | POST | Streaming query |
| `/sessions` | GET | List sessions |
| `/sessions` | POST | Create session |
| `/sessions/{id}` | DELETE | Delete session |
| `/sessions/{id}/chat` | POST | Send chat message |
| `/sessions/{id}/chat/stream` | POST | Stream chat response |
| `/sessions/{id}/interrupt` | POST | Interrupt session |

## Public Endpoints

These endpoints do NOT require authentication:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check / Root |
| `/health` | GET | Health status |

## Error Responses

### Missing Authentication (401 Unauthorized)

Request without `Authorization` header:

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test"}'
```

Response:
```json
{
  "detail": "Missing authentication credentials"
}
```

### Invalid API Key (403 Forbidden)

Request with wrong API key:

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer wrong_key" \
  -d '{"prompt": "test"}'
```

Response:
```json
{
  "detail": "Invalid authentication credentials"
}
```

## Testing

### Manual Testing

1. **Test public endpoints (should work without auth):**
   ```bash
   curl http://localhost:8000/
   curl http://localhost:8000/health
   ```

2. **Test protected endpoint without auth (should fail with 401):**
   ```bash
   curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"prompt": "test", "allowed_tools": []}'
   ```

3. **Test with invalid key (should fail with 403):**
   ```bash
   curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer wrong_key" \
     -d '{"prompt": "test", "allowed_tools": []}'
   ```

4. **Test with valid key (should succeed):**
   ```bash
   export API_KEY="your_api_key_here"
   curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $API_KEY" \
     -d '{"prompt": "Hello!", "allowed_tools": []}'
   ```

### Automated Testing

Run the provided test script:

```bash
# Install dependencies
pip install requests

# Run tests
python test_auth.py
```

This will:
- Generate a test API key
- Start the server
- Run comprehensive authentication tests
- Report results

## Docker Deployment

The `docker-compose.yml` has been updated to support API keys:

```bash
# Set API key in .env file
echo "API_KEY=$(openssl rand -hex 32)" >> .env

# Start container
docker-compose up -d

# Verify authentication is enabled (check logs)
docker-compose logs | grep "API authentication"
```

## Security Best Practices

### 1. Generate Strong Keys

Always use cryptographically secure random generation:

```bash
# Good: Cryptographically secure
openssl rand -hex 32
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Bad: Weak, predictable
echo "my-api-key-123"
```

### 2. Use HTTPS in Production

API keys in HTTP headers are visible to network observers. Always use HTTPS in production:

```bash
# Set up reverse proxy with HTTPS (nginx, caddy, etc.)
# Or use a service like Cloudflare Tunnel
```

### 3. Rotate Keys Regularly

Update your API key periodically:

```bash
# Generate new key
NEW_KEY=$(openssl rand -hex 32)

# Update .env
echo "API_KEY=$NEW_KEY" > .env

# Restart server
docker-compose restart
```

### 4. Never Commit Keys to Git

The `.env` file is already in `.gitignore`. Always use `.env.example` for documentation:

```bash
# Good: Use environment variables
cp .env.example .env
# Edit .env with real keys

# Bad: Hardcode in source
API_KEY = "hardcoded-key-123"  # Never do this!
```

### 5. Limit Key Exposure

- Don't share keys in chat/email
- Use secure password managers
- Rotate immediately if compromised

## Disabling Authentication (Development Only)

For local development, you can disable authentication by not setting `API_KEY`:

```bash
# Remove or comment out API_KEY in .env
# API_KEY=...

# Server will start with warning:
# ⚠️  API_KEY not set - authentication disabled (development only)
```

**Warning:** Never deploy to production without authentication enabled!

## Troubleshooting

### "Missing authentication credentials"

- Check that you're sending the `Authorization` header
- Verify the header format: `Authorization: Bearer YOUR_KEY`
- Make sure there's no extra whitespace

### "Invalid authentication credentials"

- Verify the API key matches the one in `.env`
- Check for typos or truncation
- Regenerate key if necessary

### Server starts but authentication not working

- Check that `API_KEY` is set in environment
- Restart server after changing `.env`
- Check server logs for authentication status

### Docker container authentication issues

- Verify `API_KEY` is in host's `.env` file
- Check docker-compose passes environment variable
- Inspect running container: `docker exec claude-agent-server env | grep API_KEY`

## Migration from Unauthenticated Server

If you have existing clients:

1. **Option 1: Gradual rollout**
   - Deploy without setting `API_KEY` (authentication disabled)
   - Update all clients to send `Authorization` header
   - Enable authentication by setting `API_KEY`

2. **Option 2: Breaking change**
   - Set `API_KEY` immediately
   - Update all clients at once
   - Clients without auth will receive 401 errors

## Future Enhancements

Possible future improvements:

- Multiple API keys with different permission levels
- API key management endpoints (create/revoke keys)
- Rate limiting per API key
- API key metadata (name, created date, last used)
- Audit logging of API key usage
- IP whitelisting
- JWT tokens with expiration

## Support

For issues or questions:
- Check server logs: `docker-compose logs -f`
- Review this guide
- Open an issue on GitHub
