# Build stage — resolve Python dependencies into a relocatable user site tree.
FROM python:3.13-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.13-slim
WORKDIR /app

# Node.js is required because the filesystem and Tavily MCP servers are Node
# packages launched over stdio. Pre-installing them globally means npx resolves
# them from PATH at startup instead of downloading on every cold start.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && \
    npm install -g @modelcontextprotocol/server-filesystem tavily-mcp && \
    npm cache clean --force && \
    apt-get purge -y --auto-remove && \
    rm -rf /var/lib/apt/lists/*

# Create the unprivileged user before copying, so the dependency tree lands in a
# home directory it can actually read. (Copying to /root/.local and then dropping
# to a non-root user leaves the packages unreadable — /root is mode 0700.)
RUN useradd -m appuser
COPY --from=build --chown=appuser:appuser /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH \
    HOME=/home/appuser \
    PYTHONUNBUFFERED=1 \
    MCP_CONFIG_PATH=/app/mcp_config.json \
    MCP_FILESYSTEM_ROOT=/app/workspace

COPY . .
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
CMD ["python", "main.py"]
