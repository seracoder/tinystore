# Serialization

How rows are (de)serialized to and from the on-disk JSON format. TinyStore never
`eval`s, `exec`s, or `pickle`s data — only `json.loads` into validated Pydantic
models.

::: tinystore.serialization
