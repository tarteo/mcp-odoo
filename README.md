# mcp-odoo

A local [Model Context Protocol](https://modelcontextprotocol.io/) server for working with Odoo records. Connect one or more Odoo instances, inspect models and fields, and search, read, create, update, or delete records through your MCP client. The server supports Odoo 18.0, 19.0, and 20.0.

## Example prompts

- "List customer's email addresses."
- "Create a partner named Northwind Trading with this email address."
- "Update this sales order's note."

## Features

- **Browse models** — list available models and inspect their fields.
- **Manage records** — search with Odoo domains and perform standard CRUD operations.
- **Connect instances** — configure separate Odoo instances.
- **Version-aware behavior** — select compatibility behavior using each instance's configured Odoo version.
- **Read-only access** — keep selected instances read-only; mutation calls are rejected for them.

## Configuration reference

The server reads `config.yaml` from the directory specified by `MCP_ODOO_RC`. If unset, it uses `~/.config/mcp-odoo`:

```text
$MCP_ODOO_RC/config.yaml
$HOME/.config/mcp-odoo/config.yaml  # when MCP_ODOO_RC is unset
```

Set `MCP_ODOO_RC` to use a different directory. Each key under `instances` is a user-chosen name for an Odoo connection, such as a company or deployment identifier. The name identifies the connection.

**Instances**

- `instances.<name>.url` *(required)* — base URL of the Odoo server.
- `instances.<name>.database` *(required)* — Odoo database name.
- `instances.<name>.username` *(required)* — Odoo user account.
- `instances.<name>.api_key` *(required)* — API key for that Odoo user. Treat it as a secret.
- `instances.<name>.version` *(required)* — Odoo version: `18.0`, `19.0`, or `20.0`.
- `instances.<name>.readonly` *(optional, default `false`)* — disallow record creation, updates, and deletion for this instance.

**General**

- `log_level` *(optional, default `info`)* — `debug`, `info`, `warning`, or `error`.

Use a dedicated Odoo user with only the access rights the MCP server needs. Keep `config.yaml` private and out of version control; never put API keys in client registration files or logs.

## Example `config.yaml`

```yaml
# ~/.config/mcp-odoo/config.yaml
instances:
  company_a:
    url: https://company-a.odoo.example.com
    database: company_a_db
    username: mcp-company-a@example.com
    api_key: "replace-with-company-a-api-key"
    version: "18.0"
    readonly: false
  company_b:
    url: https://company-b.odoo.example.com
    database: company_b_db
    username: mcp-company-b@example.com
    api_key: "replace-with-company-b-api-key"
    version: "20.0"
    readonly: true

log_level: info
```

Each configured instance must declare its version. The server does not infer a version from the URL or silently select an instance when more than one is configured.

## Read-only enforcement

Readonly is configured per instance. Read and metadata tools and both resources remain available for readonly instances. Mutation calls resolve the target instance first, then reject the operation if that instance is readonly. The check is enforced at call time, not just by hiding tools from the client.

MCP tool registration is server-wide. Therefore:

- If all configured instances are readonly, do not register `create_record`, `update_record`, or `delete_record`.
- If at least one instance is writable, register mutation tools and reject calls targeting readonly instances.

This rule allows instances to have independent readonly policies.

## Configuration and instance selection

The server loads `config.yaml` from `$MCP_ODOO_RC`, or from `~/.config/mcp-odoo` when the environment variable is unset. The top-level `instances` mapping is keyed by a stable user-chosen name. Each entry contains the Odoo URL, database, username, API key, explicit version, and optional readonly setting.

The supported version set is Odoo 18.0, 19.0, and 20.0. Versions are explicit configuration, not inferred from a connection or endpoint. Missing, malformed, or unsupported versions fail configuration validation instead of selecting a fallback adapter.

Every tool call resolves its `instance` before connecting:

- With one configured instance, omission resolves to that instance.
- With multiple instances, omission is an error; no instance is preferred by ordering.
- An unknown instance name is an error and must not trigger a retry against another instance.

Resources use instance-qualified URIs for both one- and multi-instance configurations. This gives resource identifiers stable meaning independent of how many instances are currently configured.

## Version compatibility

An instance's configured version selects a compatibility adapter. The generic CRUD contract stays consistent across supported versions; adapters isolate differences in RPC behavior, capabilities, and model metadata. Generic CRUD uses the actual model and field names accepted by that Odoo version. It does not guess that arbitrary fields in user-provided domains or value mappings should be renamed.

Version-specific domain tools should operate on semantic inputs and translate them through the selected adapter. For example, a hypothetical higher-level task that accepts a semantic priority could map that concept to a version-specific field; a field rename such as `priority` to `level` between Odoo 16.0 and 17.0 illustrates why this mapping belongs in a version adapter. This is an architectural example only: the initial supported versions are 18.0, 19.0, and 20.0, and the generic CRUD tools do not claim that mapping.

Adapters should make version selection explicit and testable. Adding support for another Odoo release requires a version adapter, compatibility tests for the shared CRUD contract, and updates to the documented support matrix.

## Run locally

Create a virtual environment and install the dependencies:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

With `config.yaml` at the default path, start the stdio server with:

```sh
.venv/bin/python -m mcp_odoo
```

For a different config directory, set `MCP_ODOO_RC` before starting the process.

## Using with OpenCode (Docker)

1. Build the image:

   ```sh
   docker build -t mcp-odoo .
   ```

2. Register the server in `opencode.json` (project root) or `~/.config/opencode/opencode.json`. Replace `/home/<you>` with the absolute path to your home directory:

   ```json
   {
     "$schema": "https://opencode.ai/config.json",
     "mcp": {
       "odoo": {
         "type": "local",
         "enabled": true,
         "command": [
           "docker", "run", "-i", "--rm",
           "-v", "/home/<you>/.config/mcp-odoo:/config:ro",
           "-e", "MCP_ODOO_RC=/config",
           "mcp-odoo"
         ]
       }
     }
   }
   ```

   Use an absolute host path; `~` is not expanded in the mount. The config directory is mounted read-only. Keep `-i`: MCP communicates over standard input and output.

3. Verify with `opencode mcp list`; the `odoo` server should show as connected.

## Tools and resources

The server exposes a standard MCP surface.

- **tools/** — high-level actions:
  - `config_info` — show the config file path and configured instance names, versions, and readonly settings; never return API keys.
  - `list_models` — list models available through the selected instance.
  - `get_model_fields` — inspect a model's fields and metadata.
  - `search_records` — search a model using an Odoo domain, optional fields, and pagination. `limit` defaults to 20 and is capped at 100; `offset` defaults to 0.
  - `read_record` — fetch a record by model and record ID, optionally selecting fields.
  - `create_record` — create a record from a field/value mapping and return its new record ID.
  - `update_record` — update a record by model and record ID using a field/value mapping.
  - `delete_record` — delete a record by model and record ID. Deletion is permanent in Odoo.
  - All instance-scoped tools accept an optional `instance` name when exactly one instance is configured. With multiple instances, `instance` is required. There is no implicit first-instance fallback.
  - Mutation tools are omitted when every configured instance is read-only. If writable instances exist, mutation tools are listed, but calls targeting a read-only instance are rejected.
- **resources/** — read-only record views:
  - `odoo://instances/{instance}/models/{model}/records` — up to 20 records from a model in the selected instance.
  - `odoo://instances/{instance}/models/{model}/records/{record_id}` — one record by ID.

Resources are always instance-qualified so their URIs remain stable when configuration changes. Odoo access rights and record rules still apply to every operation; the server does not grant access beyond the configured user's permissions.
