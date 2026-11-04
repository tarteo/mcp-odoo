# mcp-odoo

A local [Model Context Protocol](https://modelcontextprotocol.io/) server for working with Odoo records. Connect an Odoo database, inspect models and fields, and search, read, create, update, or delete records through your MCP client. The server supports Odoo 18.0, 19.0, and 20.0.

## Example prompts

- "List customer's email addresses."
- "Create a partner named Northwind Trading with this email address."
- "Update this sales order's note."
- "What are my highest priority tasks todo today?"
- "Fill in my time sheet based on this file."
-  "What messages do I have in my inbox?"

## Features

- **Manage records** — search with Odoo domains and perform standard CRUD operations.
- **Tool whitelist** — expose only the configured tools, including selected model methods from shared registry files, with three safe discovery/configuration tools always available.
- **Version-aware behavior** — select compatibility behavior using the configured Odoo version.

## Configuration reference

The server reads `config.yaml` from the directory specified by `MCP_ODOO_RC`. If unset, it uses `~/.config/mcp-odoo`:

```text
$MCP_ODOO_RC/config.yaml
$HOME/.config/mcp-odoo/config.yaml  # when MCP_ODOO_RC is unset
```

Set `MCP_ODOO_RC` to use a different directory. Each config file represents exactly one Odoo connection. To connect to multiple databases, create a separate config directory and MCP server entry for each one.

**Connection**

- `url` *(required)* — base URL of the Odoo server.
- `database` *(required)* — Odoo database name.
- `username` *(required)* — Odoo user account.
- `api_key` *(required)* — API key for that Odoo user. Treat it as a secret.
- `version` *(required)* — Odoo version: `18.0`, `19.0`, or `20.0`.

**Tool access**

- `whitelist` *(required)* — list of tools to expose. It may be empty. Available built-in names are `read_messages`, `post_message`, `schedule_activity`, `archive_records`, `search_records`, `read_record`, `create_record`, `update_record`, `delete_record`, and `exec`. It may also contain a registered Odoo method key such as `sale.order.action_confirm`.
- `registry` *(optional)* — list of method registry YAML file paths. If omitted, the bundled `registry/<version>.yaml` is used. If supplied, the listed files are merged and replace that default; include the bundled file if you want its methods too. Relative paths are resolved beside `config.yaml` first, then from the application root. Absolute paths are supported for mounted registry files.
- `config_info`, `list_models`, and `get_model_fields` are always available and do not need to be listed.
- Resource reads are allowed only when their corresponding `read_messages`, `search_records`, or `read_record` tool is whitelisted.

**General**

- `log_level` *(optional, default `info`)* — `debug`, `info`, `warning`, or `error`.

Use a dedicated Odoo user with only the access rights the MCP server needs. Keep `config.yaml` private and out of version control; never put API keys in client registration files or logs.

## Example `config.yaml`

```yaml
# ~/.config/mcp-odoo/config.yaml
url: https://company-a.odoo.example.com
database: company_a_db
username: mcp-company-a@example.com
api_key: "replace-with-company-a-api-key"
version: "18.0"

registry:
  - registry/18.0.yaml
  - /registries/mycustom.yaml

whitelist:
  - search_records
  - read_messages
  - post_message
  - read_record
  - create_record
  - update_record
  - delete_record
  - sale.order.action_confirm
  - sale.order.custom_operation

log_level: info
```

The connection version is required. The server does not infer it from the URL. The whitelist is validated against built-in tools and the loaded registry files; unknown or duplicate names are rejected. Duplicate method entries across registry files are errors. Every method must also be listed in `whitelist` before a tool is registered.

## Odoo method registry

Core method definitions live in the bundled `registry/<version>.yaml` files and are shared by every connection using this server version. These entries are curated from the corresponding official Odoo core source tree (`addons/` and `odoo/addons/`); they are not discovered from a connected database and do not include Enterprise or custom addons. A whitelist entry registers the matching method as a typed MCP tool. For example, `sale.order.action_confirm` creates the tool `odoo_sale_order_action_confirm`, with its description and parameter schema from the registry. The registry is version-specific because Odoo method availability and signatures can differ between releases.

The Odoo 18 registry includes selected CRM, project, activity, sales, purchasing, inventory, accounting, time-off, and calendar actions. This includes operations such as confirming orders, posting accounting entries, approving time off, completing activities, and emailing meeting invitations. Their descriptions call out consequential changes and external email effects. These methods are only exposed when explicitly added to `whitelist`; Odoo permissions and approval checks still apply.

To add custom methods, create another registry file and list its path in `registry`. For example, `mycustom.yaml` could contain:

```yaml
sale.order.custom_operation:
  description: Run a custom operation on selected sales orders.
  parameters:
    ids:
      type: array
      description: IDs of the sales orders to process.
      required: true
      items:
        type: integer
    note:
      type: string
      description: Optional note for the operation.
      required: false
```

Add `sale.order.custom_operation` to `whitelist` to expose the method. Each method definition requires a non-empty `description` and a `parameters` mapping. Supported parameter types are `string`, `integer`, `number`, `boolean`, `object`, and `array`; arrays require an `items` schema. Parameters are required by default; set `required: false` to make one optional. If an optional parameter is not provided, it is omitted from the Odoo call. Object parameters accept arbitrary JSON objects. The method is called through the configured Odoo account, so Odoo access rights still apply. Registry files are curated metadata, not introspection: calls to methods that are unavailable on the target database will fail in Odoo.

## Whitelist enforcement

Only whitelisted tools (plus the three always-available tools) are registered with MCP. Resource reads independently check for the matching read tool in the whitelist.

The whitelist controls MCP tool availability, not Odoo permissions. Odoo access rights and record rules still apply, so use a dedicated Odoo user with only the permissions the configured tools need.

`exec` is intentionally broad: when enabled, it can call any method on any model available to the configured Odoo user. Methods can perform arbitrary business actions, including irreversible changes or external side effects. Odoo access rights and record rules still apply, but they do not guarantee that each method independently checks access. Enable `exec` only for trusted MCP clients and consider using a dedicated Odoo account with narrowly scoped permissions. Methods whose names start with `_` are rejected.

`config_info`, `list_models`, and `get_model_fields` are always available. All other tools are registered only when listed in the root-level `whitelist`.

## Version compatibility

The configured version selects a compatibility adapter. The generic CRUD contract stays consistent across supported versions; adapters isolate differences in RPC behavior, capabilities, and model metadata. Generic CRUD uses the actual model and field names accepted by that Odoo version. It does not guess that arbitrary fields in user-provided domains or value mappings should be renamed.

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
            "-v", "/home/<you>/odoo-methods:/registries:ro",
            "-e", "MCP_ODOO_RC=/config",
           "mcp-odoo"
         ]
       }
     }
   }
   ```

   Use absolute host paths; `~` is not expanded in mounts. The config and registry directories are mounted read-only. The second volume is only needed when `config.yaml` lists custom files under `/registries`. Keep `-i`: MCP communicates over standard input and output.

3. Verify with `opencode mcp list`; the `odoo` server should show as connected.

## Using with Oh My Pi

Build the Docker image as described in [Using with OpenCode](#using-with-opencode-docker), then register the server in `.omp/agent/mcp.json` at the project root:

```json
{
  "$schema": "https://raw.githubusercontent.com/can1357/oh-my-pi/main/packages/coding-agent/src/config/mcp-schema.json",
  "mcpServers": {
    "odoo": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/home/<you>/.config/mcp-odoo:/config:ro",
        "-v", "/home/<you>/odoo-methods:/registries:ro",
        "-e", "MCP_ODOO_RC=/config",
        "mcp-odoo"
      ]
    }
  }
}
```

Replace `/home/<you>` with the absolute path to your home directory; `~` is not expanded in mounts. The config and registry directories are mounted read-only. The registry volume is only needed when `config.yaml` lists custom files under `/registries`. Keep `-i`: MCP communicates over standard input and output. Start or restart Oh My Pi, then verify with `/mcp list` and `/mcp test odoo`.

## Tools and resources

The server exposes a standard MCP surface.

- **tools/** — high-level actions:
  - `config_info` — show the config file path, connection details, and whitelist; never return the API key.
  - `list_models` — search models by technical name or label (`search`, case-insensitive substring). `limit` defaults to 50 and is capped at 200.
  - `get_model_fields` — inspect a model's fields and metadata, filtered by `search` on field name or label. `limit` defaults to 50 and is capped at 200.
  - `read_messages` — read chatter messages (newest first) of a record on a `mail.thread` model. `limit` defaults to 20 and is capped at 100; `offset` defaults to 0.
  - `post_message` — post a message, or an internal note with `internal_note`, on a `mail.thread` record and return the message ID. Treated as a mutation.
  - `schedule_activity` — schedule an activity on records for any model that implements `mail.activity.mixin`. Accepts the model, record IDs, and optional activity type, deadline, summary, note, and assigned user. Requires `schedule_activity` in the whitelist.
  - `archive_records` — archive records on a model with an active field, using Odoo's base `action_archive` behavior and any model-specific overrides. Requires `archive_records` in the whitelist.
  - `search_records` — search a model using an Odoo domain, optional fields, and pagination. `limit` defaults to 20 and is capped at 100; `offset` defaults to 0. Binary and image fields are omitted unless named in `fields`.
  - `read_record` — fetch a record by model and record ID, optionally selecting fields. Binary and image fields are omitted unless named in `fields`.
  - `create_record` — create a record from a field/value mapping and return its new record ID.
  - `update_record` — update a record by model and record ID using a field/value mapping.
  - `delete_record` — delete a record by model and record ID. Deletion is permanent in Odoo.
  - `exec` — invoke a method by model and method name, with optional record `ids` and named `params`. For example, `exec("sale.order", "action_confirm", ids=[42])` calls the method on that order. Odoo 20's JSON-2 API accepts named method parameters; supply them in `params` rather than as positional arguments. This tool is available only when `exec` is in the whitelist and may cause arbitrary business side effects.
  - Registry methods — one typed tool per whitelisted `model.method` entry, named `odoo_<model>_<method>` with dots replaced by underscores. Their descriptions and input schemas come from the versioned core registry and any additional registry files listed in `registry`.

- **resources/** — read-only record views:
  - `odoo://models/{model}/records` — up to 20 records from a model; reading requires `search_records` in the whitelist.
  - `odoo://models/{model}/records/{record_id}` — one record by ID; reading requires `read_record` in the whitelist.
  - `odoo://models/{model}/records/{record_id}/messages` — latest 20 chatter messages of a record; reading requires `read_messages` in the whitelist.

Odoo access rights and record rules still apply to every operation; the server does not grant access beyond the configured user's permissions. To connect to multiple Odoo databases, configure a separate MCP server entry and config directory for each one.

## Domain-specific shortcuts

Domain-specific tools are semantic shortcuts over common Odoo workflows. Document them separately from generic CRUD so callers can use concepts such as "high priority" without needing to know which model field represents that concept in each supported version. Each shortcut uses the configured connection's version adapter and should follow the same whitelist and Odoo access-control rules as generic tools.
