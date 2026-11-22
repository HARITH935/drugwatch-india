-- A watch only notifies about alert months published *after* it was created.
--
-- Without this, adding "telmisartan" to a watchlist would match findings in most of the archive's
-- 101 published months and send about a hundred emails at once - which is indistinguishable from
-- spam, and would get the sending domain blocked long before anybody read one. The watchlist is
-- for "tell me when something NEW is reported"; the drug pages already answer "what has been
-- reported before".
--
-- The baseline is the latest alert month in the warehouse at the moment the watch was created, so
-- it needs no clock arithmetic and no guess about when CDSCO publishes.

ALTER TABLE app.watchlist_items
    ADD COLUMN since_alert_month text NOT NULL DEFAULT '9999-12'
        CHECK (since_alert_month ~ '^\d{4}-\d{2}$');

-- The default exists only so the column can be NOT NULL on a table that may already hold rows.
-- '9999-12' is deliberately in the far future: a row that somehow missed its baseline notifies
-- about nothing, rather than about everything. Failing closed is the right direction for a
-- column that decides whether to email somebody.
COMMENT ON COLUMN app.watchlist_items.since_alert_month IS
    'Alert months at or before this are not notified: the archive''s latest month when the watch was created.';
