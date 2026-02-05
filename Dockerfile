# Claude Code SDK HTTP Server
#
# Build: docker build -t claude-sdk-server .
# Run: docker run -p 8000:8000 -v ~/.claude:/home/claude/.claude claude-sdk-server
#
# Configuration is stored in ~/.claude/settings.json (mounted into container)
#
# Security hardening based on:
# - https://docs.anthropic.com/docs/en/agent-sdk/hosting
# - https://docs.anthropic.com/docs/en/agent-sdk/secure-deployment

FROM python:3.11-slim

# Install system dependencies and Node.js (required by Claude Code CLI)
# - dumb-init: proper signal handling for PID 1
# - git: common agent task requirement
# - curl: health checks and network operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    git \
    dumb-init \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force

# Create a non-root user for security (UID 1000 as recommended)
RUN useradd -m -u 1000 -s /bin/bash claude

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY server.py .

# Set ownership and switch to non-root user
RUN chown -R claude:claude /app
USER claude

# Create directories the agent may need to write to
# Note: /home/claude/.claude will be mounted from host via docker-compose
RUN mkdir -p /home/claude/.cache /home/claude/.config /home/claude/.claude

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use dumb-init for proper signal handling
ENTRYPOINT ["/usr/bin/dumb-init", "--"]

# Run the server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
