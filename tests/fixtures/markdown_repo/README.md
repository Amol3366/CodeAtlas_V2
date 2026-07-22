# Widget Platform Documentation

The Widget Platform exposes a small HTTP API for managing widgets.

## Contents

- [Getting Started](docs/getting-started.md)
- [API Reference](docs/api-reference.md)
- [ADR-0002: Configuration format](docs/adr/0002-config-format.md)

## Overview

The platform is configured entirely through environment variables. The primary
connection is controlled by the `WIDGET_DATABASE_URL` configuration key.
