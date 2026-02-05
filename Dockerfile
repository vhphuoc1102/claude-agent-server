# Claude Agent Server Dockerfile
# Combines Python (FastAPI server) with Node.js (Claude Code CLI)

FROM python:3.11-slim

# Build arguments
ARG NODE_MAJOR=20
ARG USER_ID=1000
ARG GROUP_ID=1000

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/home/claude/.local/bin:$PATH"

# Install system dependencies and Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    git \
    dumb-init \
    ca-certificates \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create non-root user for security
RUN groupadd --gid ${GROUP_ID} claude \
    && useradd --uid ${USER_ID} --gid ${GROUP_ID} --shell /bin/bash --create-home claude

# Set working directory
WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Copy application code
COPY server.py .
COPY GUIDE.md .

# Create necessary directories
RUN mkdir -p /workspace /home/claude/.claude \
    && chown -R claude:claude /app /workspace /home/claude

# Switch to non-root user
USER claude

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use dumb-init as PID 1 for proper signal handling
ENTRYPOINT ["/usr/bin/dumb-init", "--"]

# Start the server
CMD ["python", "server.py"]
