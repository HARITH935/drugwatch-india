-- The application's own tables (plan §8.3). They live in the `app` schema, which the
-- `drugwatch_api` role owns; `gold` belongs to dbt and this migration never touches it.
--
-- Two shapes here come from Phase 9's opening decisions rather than from §8.3's four-row table:
--
--   * **The watchlist stores a search term, not a product id** (decision D). Phase 4 deliberately
--     did not merge the 5,651 differently-printed product names - "Paracetamol Tablets IP 500 mg"
--     and "Paracetamol Tab. 500mg" are two rows - so a watch pinned to one exact product would
--     silently miss the same medicine printed another way. For somebody watching their own
--     medicine, a missed alert is worse than an extra email.
--   * **An account must prove its email before it is ever written to** (decision E). Without it,
--     anyone can register with a stranger's address, add watch terms, and the site emails that
--     stranger about medicine alerts under CDSCO's name.

CREATE TABLE app.users (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Stored lower-case, and the CHECK is what makes that true rather than hoped for: without it
    -- "A@b.com" and "a@b.com" become two accounts and the unique index below stops meaning
    -- anything.
    email           text        NOT NULL UNIQUE CHECK (email = lower(email) AND email LIKE '%@%'),
    password_hash   text        NOT NULL,
    role            text        NOT NULL DEFAULT 'USER' CHECK (role IN ('USER', 'ADMIN')),
    -- Decision E. No notification may be sent to an address that has not been confirmed.
    email_verified  boolean     NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Verification links, held as a HASH of the token, never the token itself. The same reasoning as
-- refresh tokens below: a leaked database should not hand anybody a working link.
CREATE TABLE app.email_verifications (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint      NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    token_hash  text        NOT NULL UNIQUE,
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX email_verifications_user_idx ON app.email_verifications (user_id);

CREATE TABLE app.watchlist_items (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint      NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    -- What the user typed, kept so it can be shown back to them unchanged.
    term        text        NOT NULL CHECK (length(btrim(term)) BETWEEN 3 AND 100),
    -- The normalised form that matching actually uses. Three characters minimum because a
    -- one-letter term would match most of the archive and email somebody every month.
    term_norm   text        NOT NULL CHECK (term_norm = lower(term_norm)),
    created_at  timestamptz NOT NULL DEFAULT now(),
    -- One watch per term per person: re-adding the same medicine must not double the emails.
    CONSTRAINT watchlist_items_unique_per_user UNIQUE (user_id, term_norm)
);
CREATE INDEX watchlist_items_user_idx ON app.watchlist_items (user_id);
CREATE INDEX watchlist_items_term_idx ON app.watchlist_items (term_norm);

-- What has already been sent. The UNIQUE constraint is the whole point of the table: it makes a
-- duplicate notification impossible in the database rather than unlikely in the code. A retry
-- after a half-finished run, two schedulers overlapping, or a redeploy mid-send all collide with
-- it instead of emailing somebody twice about the same alert month.
CREATE TABLE app.alert_notifications (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id           bigint      NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    watchlist_item_id bigint      NOT NULL REFERENCES app.watchlist_items (id) ON DELETE CASCADE,
    -- 'YYYY-MM', the same spelling gold.fact_nsq_sample.alert_month uses.
    alert_month       text        NOT NULL CHECK (alert_month ~ '^\d{4}-\d{2}$'),
    findings_matched  integer     NOT NULL CHECK (findings_matched > 0),
    sent_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT alert_notifications_once UNIQUE (watchlist_item_id, alert_month)
);
CREATE INDEX alert_notifications_user_idx ON app.alert_notifications (user_id);

-- Refresh tokens, stored as a hash. If this table leaks, what leaks is a list of hashes that
-- cannot be presented to the API - the same reason passwords are not stored either.
CREATE TABLE app.refresh_tokens (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint      NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    token_hash  text        NOT NULL UNIQUE,
    expires_at  timestamptz NOT NULL,
    -- Set when the token is used or logged out, rather than deleting the row: a token presented
    -- twice is a signal worth being able to see, not a row to make disappear.
    revoked_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX refresh_tokens_user_idx ON app.refresh_tokens (user_id);
