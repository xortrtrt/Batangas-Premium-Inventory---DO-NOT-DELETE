# Database alignment — 12 November 2026

Neon project `BP Inventory` (`restless-king-74281392`), production branch
`br-floral-wind-b34fcw8g`, database `neondb`, was upgraded from migration 009
through 012 before this release. Existing migration checksums 001–009 matched
the repository. Migrations 010–012 were applied together in one transaction with
the migration advisory lock and bounded lock/statement timeouts.

The Windows local database on port 55434 and the Docker database are also at
migration 012. Schema fingerprints match across all three environments:

| Schema category | Objects | MD5 fingerprint |
| --- | ---: | --- |
| Columns | 170 | `bc54890539b30ac440bcfc30ad32bb0c` |
| Constraints | 136 | `a65c0a6dd6f5c506159ab0c58aa9590b` |
| Indexes | 43 | `8ae9903931663b866141b0d8ab4828a0` |
| Application triggers | 15 | `4ed63be6957fb0a64dfa8ab191c0a8d6` |
| Migration versions and SHA-256 checksums | 12 | `cbd807f63354147ca9dd93bdfdaee093` |

Column comparison uses names, types, nullability, defaults, precision, and
identity settings. Physical column positions are excluded because previously
dropped columns leave different internal positions without changing behavior.
PostgreSQL 18 catalog-only NOT NULL constraint rows are excluded from constraint
comparison with Neon PostgreSQL 16; column nullability is checked separately.

Neon's two legacy tables `account_activation_tokens` and
`account_password_otps` were retained and excluded from the application schema
comparison. No production tables were deleted, and local inventory data was not
copied to production.

All 23 existing Neon batches received `batch_date = received_date`. Their original
fields retained their pre-migration fingerprint
`14cdd6e2c4391a140fbe57d7599f32f5`. All 220 inventory movements retained their
fingerprint `cdd1a730f9afd610dbe474b6ca3c9e0e`.

The three supply tables are present with their indexes, foreign keys, checks,
and immutable-history triggers. Startup continues to use
`tools/migrate_database.py` to apply ordered, checksum-protected migrations.
Credentials and local database dumps remain outside version control.
