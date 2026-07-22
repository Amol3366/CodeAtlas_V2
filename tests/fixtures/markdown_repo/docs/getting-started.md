# Getting Started

## Installation

```bash
pip install widget-platform
```

## Running the server

You MUST set `WIDGET_DATABASE_URL` before starting. You SHOULD also set
`WIDGET_LOG_LEVEL`.

```bash
export WIDGET_DATABASE_URL="postgresql://localhost/widgets"
widget serve
```

## Configuration keys

| Key | Required | Default | Description |
|---|---|---|---|
| `WIDGET_DATABASE_URL` | yes | — | Database connection string |
| `WIDGET_LOG_LEVEL` | no | `info` | Logging verbosity |
| `WIDGET_PORT` | no | `8080` | HTTP listen port |

See the [API Reference](api-reference.md) for endpoint details.
