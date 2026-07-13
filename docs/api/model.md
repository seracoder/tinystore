# Model & Field

Define tables with `Model` and `Field`. `Model` subclasses `pydantic.BaseModel`,
so all Pydantic validation applies; `Field` adds TinyStore metadata
(`primary_key`, `unique`, `index`, `foreign_key`, ...) on top.

## `Model`

::: tinystore.model

## `Field`

::: tinystore.fields
