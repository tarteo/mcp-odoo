FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mcp_odoo ./mcp_odoo
ENV MCP_ODOO_RC=/config
ENTRYPOINT ["python", "-m", "mcp_odoo"]
