# Build stage — resolve Python dependencies into a relocatable user site tree.
FROM python:3.13-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.13-slim
WORKDIR /app

# Node.js is required because the filesystem and Tavily MCP servers are Node
# packages launched over stdio. Node 22 comes from the official image rather than
# Debian's apt package (Node 20), because the fetch server's page extractor
# depends on jsdom releases that refuse to run below Node 22.
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Pre-installing the MCP servers globally means npx resolves them from PATH at
# startup instead of downloading on every cold start.
RUN npm install -g @modelcontextprotocol/server-filesystem tavily-mcp && \
    npm cache clean --force

# Create the unprivileged user before copying, so the dependency tree lands in a
# home directory it can actually read. (Copying to /root/.local and then dropping
# to a non-root user leaves the packages unreadable — /root is mode 0700.)
RUN useradd -m appuser
COPY --from=build --chown=appuser:appuser /root/.local /home/appuser/.local

# The fetch server's HTML extractor (readabilipy) runs `npm install` on its first
# call if its JavaScript dependencies are missing. At request time that npm output
# lands on the MCP stdio channel and corrupts the JSON-RPC stream, so install them
# here, at build time, instead.
RUN cd /home/appuser/.local/lib/python3.13/site-packages/readabilipy/javascript && \
    npm install --omit=dev --no-fund --no-audit && \
    npm cache clean --force && \
    chown -R appuser:appuser .
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
