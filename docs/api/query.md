# Queries

`db.select(Model)` returns a `SelectQuery`. Chain `.where(...)`, `.order_by(...)`,
`.limit(...)`, `.offset(...)`, and `.join(...)` to build it, then call a terminal
method (`.all()`, `.first()`, `.one()`, `.count()`, `.exists()`).

## SelectQuery

::: tinystore.query.query

## Joins

::: tinystore.query.joins

## Expressions

Field proxies (`User.age`) build typed expressions when compared. Predicates
combine with `&` (and), `|` (or), and `~` (not).

::: tinystore.query.expressions
