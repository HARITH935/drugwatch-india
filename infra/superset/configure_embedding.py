"""Set up Superset for embedding: the guest role, the token-issuing account, and the allowlist.

Phase 9 step 7. Three separate things, each built from nothing rather than by granting a bundle -
the same approach as Phase 6's Public role, and for the same reason: a role assembled from a
built-in template carries permissions nobody chose.

1. **The `EmbeddedViewer` role**, which a guest token carries. Its permissions are **copied from
   the existing Public role** rather than restated here. An embedded dashboard should be able to do
   exactly what an anonymous visitor can and nothing more, and copying means that stays true when
   Phase 12 tightens Public - instead of two lists drifting apart, one of which somebody forgets.

2. **The `GuestTokenIssuer` role**, holding exactly one permission: `can_grant_guest_token`. It can
   mint a token and do nothing else - not read a dashboard, not run a query, not see a dataset.

3. **The service account** the API logs in as, holding only that one role. If its password leaks,
   what leaks is the ability to mint tokens for allowlisted dashboards: bad, and far short of an
   admin session. Phase 6's `configure_public_role.py` deliberately refused
   `can_grant_guest_token` to anonymous visitors and left a note that Phase 9 would do this
   server-side; this is that.

It also marks the allowlisted dashboards as embeddable and prints their embedded UUIDs, which are
what the API's allowlist maps to.

Idempotent: roles are set to exactly these permissions on every run, so anything added by hand in
the UI is removed again.

Run from the repo root, with the stack up. The -e flags matter: this reads the service account's
credentials from the environment, and `docker compose exec` passes the host's only when named:
    set -a && . ./.env && set +a && \
        docker compose exec -T -e SUPERSET_EMBED_USERNAME -e SUPERSET_EMBED_PASSWORD \
        superset python - < infra/superset/configure_embedding.py
"""

import os

from superset.app import create_app

GUEST_ROLE = "EmbeddedViewer"
ISSUER_ROLE = "GuestTokenIssuer"
SOURCE_ROLE = "Public"

# The dashboards an embedded page may ask for. Anything not named here cannot be embedded, so a
# dashboard added later is private until somebody lists it on purpose.
ALLOWED_DASHBOARD_SLUGS = (
    "manufacturer-reporting",
    "states",
    "drug-classes",
    "spurious-reports",
)

# The only permission the issuing account needs.
#
# On `SecurityRestApi`, not `Superset`: the first version of this script guessed the latter and the
# run stopped with "does not exist in this build" rather than silently granting nothing. Found by
# asking Superset's own permission tables - the same habit as Phase 6, where an invented
# `can_read on ChartDataRestApi` was reported as NOT FOUND instead of being skipped.
ISSUER_PERMISSION = ("can_grant_guest_token", "SecurityRestApi")


def main() -> None:
    app = create_app()
    with app.app_context():
        from superset import security_manager
        from superset.extensions import db

        session = db.session

        # --- 1. the guest role, copied from Public ------------------------------------------
        source = security_manager.find_role(SOURCE_ROLE)
        if source is None:
            raise SystemExit(
                f"the {SOURCE_ROLE} role does not exist yet. Run configure_public_role.py first:"
                " the embedded viewer is defined as 'whatever an anonymous visitor may do'."
            )

        guest = security_manager.find_role(GUEST_ROLE) or security_manager.add_role(GUEST_ROLE)
        guest.permissions = list(source.permissions)
        session.commit()
        print(f"{GUEST_ROLE}: {len(guest.permissions)} permission(s), copied from {SOURCE_ROLE}")

        # --- 2. the issuer role, exactly one permission -------------------------------------
        issuer = security_manager.find_role(ISSUER_ROLE) or security_manager.add_role(ISSUER_ROLE)
        wanted = security_manager.find_permission_view_menu(*ISSUER_PERMISSION)
        if wanted is None:
            raise SystemExit(
                f"{ISSUER_PERMISSION[0]} on {ISSUER_PERMISSION[1]} does not exist in this build."
                " Is EMBEDDED_SUPERSET enabled in superset_config.py? The permission only appears"
                " once the feature flag is on."
            )
        # Set, not append: the role holds this and nothing else, on every run.
        issuer.permissions = [wanted]
        session.commit()
        print(f"{ISSUER_ROLE}: {[str(p) for p in issuer.permissions]}")

        # --- 3. the service account ---------------------------------------------------------
        username = os.environ["SUPERSET_EMBED_USERNAME"]
        password = os.environ["SUPERSET_EMBED_PASSWORD"]
        account = security_manager.find_user(username=username)
        if account is None:
            account = security_manager.add_user(
                username=username,
                first_name="Embed",
                last_name="Service",
                email=f"{username}@drugwatch.local",
                role=issuer,
                password=password,
            )
            print(f"created the service account {username}")
        else:
            # Roles set rather than added: an account that picked up Admin by hand loses it here.
            account.roles = [issuer]
            security_manager.reset_password(account.id, password)
            print(f"updated the service account {username}")
        session.commit()
        print(f"  roles: {[role.name for role in account.roles]}")

        # --- 4. the allowlist ---------------------------------------------------------------
        from superset.models.dashboard import Dashboard

        print("\nembeddable dashboards:")
        for slug in ALLOWED_DASHBOARD_SLUGS:
            dashboard = session.query(Dashboard).filter_by(slug=slug).one_or_none()
            if dashboard is None:
                print(f"  {slug:24s} NOT FOUND - build it first")
                continue
            embedded = dashboard.embedded
            if not embedded:
                from superset.daos.dashboard import EmbeddedDashboardDAO

                # No row-level security rules: these dashboards are public CDSCO data, and every
                # viewer sees the same thing. An RLS rule here would imply a per-viewer slice of
                # the archive, which does not exist.
                EmbeddedDashboardDAO.upsert(dashboard, [])
                session.commit()
                dashboard = session.query(Dashboard).filter_by(slug=slug).one()
                embedded = dashboard.embedded
            print(f"  {slug:24s} {embedded[0].uuid}")

        print("\nThese UUIDs are what the API's allowlist maps to (drugwatch.superset.dashboards).")


if __name__ == "__main__":
    main()
