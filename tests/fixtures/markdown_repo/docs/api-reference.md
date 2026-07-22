# API Reference

## Widgets

### `POST /widgets`

Creates a widget. Implemented by `WidgetController.create` in
`src/controllers/widget_controller.py`.

Request body:

```json
{ "name": "string", "color": "string" }
```

### `GET /widgets/{id}`

Returns a single widget. Implemented by `WidgetController.get`.

## Errors

All endpoints return an error envelope:

```json
{ "error": { "code": "string", "message": "string" } }
```
