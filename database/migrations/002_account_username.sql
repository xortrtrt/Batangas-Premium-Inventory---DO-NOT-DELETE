ALTER TABLE accounts ADD COLUMN IF NOT EXISTS username text;
CREATE UNIQUE INDEX IF NOT EXISTS accounts_username_lower_unique
    ON accounts (lower(username)) WHERE username IS NOT NULL;
