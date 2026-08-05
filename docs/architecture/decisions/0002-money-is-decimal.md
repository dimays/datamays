# 0002 — Money is `Decimal`, never `float`

**Status:** accepted
**Reverse cost:** high — every stored column and every aggregate assumes it

## Context

Python's `float` is IEEE 754 binary. It cannot represent 0.10 exactly. Summing
a few thousand transactions in floats accumulates error that shows up as a
budget which is off by a cent, then a few cents, and never reconciles against
a bank statement.

## Decision

Every money column is `DecimalField`, defined through `money_field()` in
`finance/models/base.py`. Nothing else defines a money column.

`float()` is permitted at exactly one boundary: serializing a number into JSON
for Chart.js, where it is read once and never written back.

## Why it matters here specifically

This app's whole purpose is answering "can we afford this?" against a budget.
A number that is *almost* right is indistinguishable from a number that is
right, until the month it isn't — and by then there is no way to tell which
figures were wrong or since when.

## Notes

There is one place a float round-trip actually caused a bug and was fixed:
`observed_value` in `finance/services/alerts.py`. It is worth reading if you
are tempted to relax this — the failure was silent and the alert simply did
not fire.

Aggregates come back from the ORM as `Decimal`. Keep them that way until the
last possible moment.
