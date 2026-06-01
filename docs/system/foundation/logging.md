# Logging

Runtime code uses structured JSON logs through `shkandal_common.logging`.

Required fields:

- `timestamp`
- `name`
- `level`
- `message`

Optional context fields are included for future request and review workflows:

- `trace_id`
- `session_id`
- `user_id`
