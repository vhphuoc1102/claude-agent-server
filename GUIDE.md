# Claude SDK Server - API Guide

A FastAPI-based HTTP server that exposes the Claude Agent SDK as REST endpoints, enabling integration of Claude AI agent capabilities with external applications.

## Table of Contents

- [Quick Start](#quick-start)
- [API Endpoints](#api-endpoints)
  - [Health Check](#health-check)
  - [One-Shot Query](#one-shot-query)
  - [Session Management](#session-management)
  - [Chat Endpoints](#chat-endpoints)
- [Configuration Options](#configuration-options)
- [Docker Deployment](#docker-deployment)
- [Advanced Usage](#advanced-usage)

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20.x (required for Claude Code CLI)
- Anthropic API Key

### Installation

```bash
# Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create a `.env` file from the example:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```env
PORT=8000
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_BASE_URL=        # Optional: custom API base URL
```

### Running the Server

```bash
# Run directly with Python
python server.py

# Or use uvicorn with custom options
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

### Using Docker

```bash
# Set your API key in environment
export ANTHROPIC_API_KEY=your_api_key_here

# Run with Docker Compose
docker-compose up -d
```

---

## API Endpoints

### Health Check

#### GET `/`

Root endpoint for basic health check.

**Request:**
```bash
curl http://localhost:8000/
```

**Response:**
```json
{
  "status": "ok",
  "service": "claude-sdk-server"
}
```

---

#### GET `/health`

Health check endpoint for monitoring.

**Request:**
```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "healthy"
}
```

---

### One-Shot Query

#### POST `/query`

Execute a single query without session persistence. Best for standalone tasks.

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `prompt` | string | Yes | - | The prompt/question to send |
| `system_prompt` | string | No | null | System context for the agent |
| `max_turns` | integer | No | null | Maximum agentic turns allowed |
| `allowed_tools` | array | No | `["Read", "Grep", "Glob"]` | Tools the agent can use |
| `permission_mode` | string | No | null | Permission mode (see Configuration) |
| `cwd` | string | No | null | Working directory for file operations |
| `include_custom_tools` | boolean | No | true | Include built-in custom tools |

**Request:**
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What files are in the current directory?",
    "allowed_tools": ["Bash", "Glob"],
    "cwd": "/workspace"
  }'
```

**Response:**
```json
{
  "result": "The current directory contains: server.py, requirements.txt, Dockerfile...",
  "session_id": "abc123-def456-ghi789",
  "is_error": false,
  "total_cost_usd": 0.0234,
  "duration_ms": 1523
}
```

**Example - Code Analysis:**
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Analyze the server.py file and explain its main components",
    "system_prompt": "You are a senior Python developer. Provide concise technical analysis.",
    "allowed_tools": ["Read", "Grep"],
    "cwd": "/workspace",
    "max_turns": 5
  }'
```

**Example - Math Calculation (Custom Tool):**
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Calculate: (25 * 4) + (100 / 5)",
    "include_custom_tools": true
  }'
```

---

#### POST `/query/stream`

Execute a query with real-time streaming response (Server-Sent Events).

**Request:** Same as `/query`

```bash
curl -X POST http://localhost:8000/query/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "prompt": "Write a Python function to calculate fibonacci numbers",
    "allowed_tools": ["Write"],
    "cwd": "/workspace"
  }'
```

**Response Stream:**
```
data: {"type": "text", "text": "I'll create a fibonacci function"}

data: {"type": "tool_use", "name": "Write", "input": {"file_path": "/workspace/fib.py", "content": "..."}}

data: {"type": "tool_result", "tool_use_id": "tool_123", "content": "File written successfully"}

data: {"type": "text", "text": "I've created the fibonacci function..."}

data: {"type": "result", "result": "Created fib.py with fibonacci implementation", "session_id": "abc123", "is_error": false, "cost": 0.0156}

data: [DONE]
```

---

### Session Management

Sessions allow multi-turn conversations with context preservation.

#### POST `/sessions`

Create a new persistent session.

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `system_prompt` | string | No | null | System context |
| `allowed_tools` | array | No | `["Read", "Write", "Edit", "Bash", "Grep", "Glob"]` | Allowed tools |
| `permission_mode` | string | No | `"acceptEdits"` | Permission mode |
| `cwd` | string | No | null | Working directory |
| `include_custom_tools` | boolean | No | true | Include custom tools |

**Request:**
```bash
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "system_prompt": "You are a helpful coding assistant specialized in Python development.",
    "allowed_tools": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    "permission_mode": "acceptEdits",
    "cwd": "/workspace"
  }'
```

**Response:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "created"
}
```

---

#### GET `/sessions`

List all active sessions.

**Request:**
```bash
curl http://localhost:8000/sessions
```

**Response:**
```json
{
  "sessions": [
    "550e8400-e29b-41d4-a716-446655440000",
    "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
  ],
  "count": 2
}
```

---

#### DELETE `/sessions/{session_id}`

Close and delete a session.

**Request:**
```bash
curl -X DELETE http://localhost:8000/sessions/550e8400-e29b-41d4-a716-446655440000
```

**Response:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "deleted"
}
```

---

### Chat Endpoints

#### POST `/sessions/{session_id}/chat`

Send a message in an existing session (non-streaming).

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | Yes | The message to send |

**Request:**
```bash
curl -X POST http://localhost:8000/sessions/550e8400-e29b-41d4-a716-446655440000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Create a hello world Python script"
  }'
```

**Response:**
```json
{
  "response": "I've created a hello world script at /workspace/hello.py with the following content...",
  "is_complete": true
}
```

**Multi-Turn Conversation Example:**
```bash
# Turn 1: Create a file
curl -X POST http://localhost:8000/sessions/{session_id}/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Create a Python class called Calculator with add and subtract methods"}'

# Turn 2: Modify the file (session remembers context)
curl -X POST http://localhost:8000/sessions/{session_id}/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Add multiply and divide methods to the Calculator class"}'

# Turn 3: Add tests
curl -X POST http://localhost:8000/sessions/{session_id}/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Create unit tests for all Calculator methods"}'
```

---

#### POST `/sessions/{session_id}/chat/stream`

Send a message with streaming SSE response.

**Request:**
```bash
curl -X POST http://localhost:8000/sessions/550e8400-e29b-41d4-a716-446655440000/chat/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "message": "Refactor the Calculator class to use type hints"
  }'
```

**Response Stream:**
```
data: {"type": "text", "text": "I'll add type hints to the Calculator class..."}

data: {"type": "tool_use", "name": "Edit", "input": {"file_path": "/workspace/calculator.py", ...}}

data: {"type": "tool_result", "tool_use_id": "tool_456", "content": "File edited"}

data: {"type": "done", "session_id": "550e8400-e29b-41d4-a716-446655440000"}

data: [DONE]
```

---

#### POST `/sessions/{session_id}/interrupt`

Interrupt the current running task in a session.

**Request:**
```bash
curl -X POST http://localhost:8000/sessions/550e8400-e29b-41d4-a716-446655440000/interrupt
```

**Response:**
```json
{
  "status": "interrupted",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

## Configuration Options

### Permission Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `default` | Standard restrictions, requires approval | Production with user oversight |
| `acceptEdits` | Auto-accepts file edits | Development automation |
| `plan` | Planning mode only | Architecture review |
| `bypassPermissions` | Full access (use with caution) | Trusted automation pipelines |

### Available Tools

**Standard Tools:**

| Tool | Description |
|------|-------------|
| `Read` | Read file contents |
| `Write` | Create/overwrite files |
| `Edit` | Edit existing files |
| `Bash` | Execute shell commands |
| `Grep` | Search file contents |
| `Glob` | Find files by pattern |

**Custom Tools (when `include_custom_tools: true`):**

| Tool | Description | Example |
|------|-------------|---------|
| `mcp__tools__get_server_time` | Get current server time | Returns formatted timestamp |
| `mcp__tools__calculate` | Safe math calculations | `"(25 * 4) + 10"` |

---

## Docker Deployment

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |

### Docker Compose

```yaml
version: '3.8'
services:
  claude-server:
    build: .
    ports:
      - "8000:8000"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      - ./workspace:/workspace
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '1.0'
```

### Build and Run

```bash
# Build image
docker-compose build

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

---

## Advanced Usage

### Workflow: Code Review Assistant

```bash
# 1. Create a review session
SESSION=$(curl -s -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "system_prompt": "You are a code reviewer. Analyze code for bugs, security issues, and best practices.",
    "allowed_tools": ["Read", "Grep", "Glob"],
    "cwd": "/workspace/my-project"
  }' | jq -r '.session_id')

# 2. Request review
curl -X POST http://localhost:8000/sessions/$SESSION/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Review all Python files in src/ for potential issues"}'

# 3. Ask follow-up questions
curl -X POST http://localhost:8000/sessions/$SESSION/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Which of these issues are critical and need immediate attention?"}'

# 4. Cleanup
curl -X DELETE http://localhost:8000/sessions/$SESSION
```

### Workflow: Automated Testing Pipeline

```bash
# One-shot test execution
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Run pytest on the tests/ directory and summarize any failures",
    "allowed_tools": ["Bash", "Read"],
    "permission_mode": "bypassPermissions",
    "cwd": "/workspace/my-project",
    "max_turns": 10
  }'
```

### Workflow: Documentation Generator

```bash
# Create session for documentation
SESSION=$(curl -s -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "system_prompt": "You are a technical writer. Generate clear, concise documentation.",
    "allowed_tools": ["Read", "Write", "Glob"],
    "permission_mode": "acceptEdits",
    "cwd": "/workspace"
  }' | jq -r '.session_id')

# Generate API docs
curl -X POST http://localhost:8000/sessions/$SESSION/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Read all Python files and generate API documentation in docs/API.md"}'
```

### JavaScript/TypeScript Client Example

```javascript
// Using fetch API
async function queryClaudeSDK(prompt, options = {}) {
  const response = await fetch('http://localhost:8000/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt,
      allowed_tools: options.tools || ['Read', 'Grep', 'Glob'],
      cwd: options.cwd || '/workspace',
      max_turns: options.maxTurns || 5
    })
  });
  return response.json();
}

// Streaming example
async function* streamQuery(prompt) {
  const response = await fetch('http://localhost:8000/query/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream'
    },
    body: JSON.stringify({ prompt })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const lines = decoder.decode(value).split('\n');
    for (const line of lines) {
      if (line.startsWith('data: ') && line !== 'data: [DONE]') {
        yield JSON.parse(line.slice(6));
      }
    }
  }
}
```

### Python Client Example

```python
import requests
import json

class ClaudeSDKClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.session_id = None

    def query(self, prompt, **kwargs):
        """Execute one-shot query"""
        response = requests.post(
            f"{self.base_url}/query",
            json={"prompt": prompt, **kwargs}
        )
        return response.json()

    def create_session(self, **kwargs):
        """Create persistent session"""
        response = requests.post(
            f"{self.base_url}/sessions",
            json=kwargs
        )
        data = response.json()
        self.session_id = data["session_id"]
        return data

    def chat(self, message):
        """Send message in session"""
        if not self.session_id:
            raise ValueError("No active session")
        response = requests.post(
            f"{self.base_url}/sessions/{self.session_id}/chat",
            json={"message": message}
        )
        return response.json()

    def close_session(self):
        """Close current session"""
        if self.session_id:
            requests.delete(f"{self.base_url}/sessions/{self.session_id}")
            self.session_id = None

# Usage
client = ClaudeSDKClient()
result = client.query("List Python files", allowed_tools=["Glob"], cwd="/workspace")
print(result["result"])
```

### Structured Outputs

Request structured, validated JSON responses from Claude by providing a JSON Schema. The agent can still use any tools it needs, but returns data in your specified format.

#### Basic Example

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Research Anthropic and provide key company information",
    "output_format": {
      "type": "json_schema",
      "schema": {
        "type": "object",
        "properties": {
          "company_name": {"type": "string"},
          "founded_year": {"type": "number"},
          "headquarters": {"type": "string"}
        },
        "required": ["company_name"]
      }
    }
  }'
```

**Response:**
```json
{
  "result": "Research completed successfully.",
  "session_id": "abc123",
  "is_error": false,
  "total_cost_usd": 0.0234,
  "duration_ms": 2156,
  "structured_output": {
    "company_name": "Anthropic",
    "founded_year": 2021,
    "headquarters": "San Francisco, CA"
  },
  "subtype": "success"
}
```

#### Session with Structured Output

Configure structured outputs when creating a session - all responses in that session will return structured data:

```bash
# Create session with output format
SESSION=$(curl -s -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "system_prompt": "You are a data extraction assistant",
    "allowed_tools": ["Read", "Grep", "Glob"],
    "output_format": {
      "type": "json_schema",
      "schema": {
        "type": "object",
        "properties": {
          "todos": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "text": {"type": "string"},
                "file": {"type": "string"},
                "line": {"type": "number"}
              },
              "required": ["text", "file", "line"]
            }
          },
          "total_count": {"type": "number"}
        },
        "required": ["todos", "total_count"]
      }
    }
  }' | jq -r '.session_id')

# Send message - response will be structured
curl -X POST http://localhost:8000/sessions/$SESSION/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Find all TODO comments in Python files"}'
```

**Response:**
```json
{
  "response": "Found 5 TODO comments across 3 files",
  "is_complete": true,
  "structured_output": {
    "todos": [
      {"text": "Add error handling", "file": "server.py", "line": 142},
      {"text": "Implement caching", "file": "utils.py", "line": 89}
    ],
    "total_count": 5
  },
  "subtype": "success"
}
```

#### Streaming with Structured Output

Streaming responses include structured output in the final result message:

```bash
curl -X POST http://localhost:8000/query/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "prompt": "List all Python files and count lines of code",
    "allowed_tools": ["Glob", "Read"],
    "output_format": {
      "type": "json_schema",
      "schema": {
        "type": "object",
        "properties": {
          "files": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "path": {"type": "string"},
                "lines": {"type": "number"}
              }
            }
          },
          "total_lines": {"type": "number"}
        }
      }
    }
  }'
```

**Stream output:**
```
data: {"type": "text", "text": "I'll find all Python files and count their lines..."}

data: {"type": "tool_use", "name": "Glob", "input": {"pattern": "**/*.py"}}

data: {"type": "result", "result": "Analysis complete", "structured_output": {"files": [{"path": "server.py", "lines": 671}], "total_lines": 671}, "subtype": "success"}

data: [DONE]
```

#### Pydantic Integration (Python)

Generate JSON schemas from Pydantic models for type safety:

```python
from pydantic import BaseModel
import requests

class CodeStats(BaseModel):
    total_files: int
    total_lines: int
    languages: dict[str, int]

# Get JSON schema from Pydantic model
schema = CodeStats.model_json_schema()

# Use in request
response = requests.post(
    "http://localhost:8000/query",
    json={
        "prompt": "Analyze code statistics for this project",
        "output_format": {
            "type": "json_schema",
            "schema": schema
        }
    }
)

# Validate response with Pydantic
if response.json()["subtype"] == "success":
    stats = CodeStats.model_validate(response.json()["structured_output"])
    print(f"Total lines: {stats.total_lines}")
```

#### Error Handling

Always check the `subtype` field to handle structured output errors:

| Subtype | Meaning |
|---------|---------|
| `success` | Output generated and validated successfully |
| `error_max_structured_output_retries` | Could not produce valid output after retries |

```bash
RESPONSE=$(curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Extract data...",
    "output_format": {...}
  }')

# Check if successful
echo $RESPONSE | jq -r 'if .subtype == "success" then .structured_output else "Error: " + .subtype end'
```

#### Best Practices

1. **Keep schemas simple** - Start with basic types and add complexity as needed
2. **Make fields optional** - Use `required` only for essential fields
3. **Use clear prompts** - Help Claude understand what data to extract
4. **Validate responses** - Always check `subtype` before using `structured_output`
5. **Test schemas** - Verify your schema produces expected results with sample queries

---

## Error Handling

### Common HTTP Status Codes

| Code | Meaning | Resolution |
|------|---------|------------|
| 200 | Success | Request completed |
| 404 | Session not found | Check session_id is valid |
| 422 | Validation error | Check request body format |
| 500 | Server error | Check server logs |

### Error Response Format

```json
{
  "detail": "Session not found: invalid-session-id"
}
```

---

## Rate Limits & Best Practices

1. **Use sessions for multi-turn tasks** - Avoids recreating context
2. **Set appropriate `max_turns`** - Prevents runaway agents
3. **Limit tools to what's needed** - Improves security and focus
4. **Use streaming for long tasks** - Better user experience
5. **Clean up sessions** - Free server resources when done

---

## Documentation Reference

See the `documents/` directory for detailed guides:

- `PYTHON_SDK.md` - Complete Python SDK reference
- `CUSTOM_TOOLS.md` - Creating custom tools
- `SESSION_MANAGEMENT.md` - Session handling patterns
- `SECURE_DEPLOY.md` - Security hardening
- `HOSTING_AGENT.md` - Deployment patterns
- `CONFIGURE_PERMISSION.md` - Permission modes
