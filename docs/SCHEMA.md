# Database Schema Reference

Schema source: `db/schema.sql`

## Table: `images`

- `id` - autoincrement primary key
- `publisher` - image publisher (e.g., Canonical)
- `image` - Azure offer name
- `sku` - image SKU
- `version` - image version
- `region` - Azure region
- `date_added` - first discovered timestamp (UTC ISO8601)
- `last_modified` - row update timestamp (UTC ISO8601)
- `last_checked` - latest scan timestamp (UTC ISO8601)
- `validated` - state machine:
  - `unknown`
  - `known_supported`
  - `known_unsupported`

## Constraints

- Unique tuple:
  - `(publisher, image, sku, version, region)`

## Indexes

- `idx_validated`
- `idx_region`
- `idx_publisher`

## Data Semantics

- A newly discovered marketplace image is inserted as `unknown`.
- LISA testing phase updates `validated` to known values.
- Historical versions remain in DB for audit and trend analysis.
