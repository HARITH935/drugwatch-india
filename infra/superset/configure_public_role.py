"""Give Superset's anonymous "Public" role exactly enough permission to read the dashboards.

Phase 6 step 4. Runs INSIDE the superset container, where Superset's own security manager lives:

    docker compose exec -T superset python - < infra/superset/configure_public_role.py

**Why not `PUBLIC_ROLE_LIKE = "Gamma"`.** That is the shortcut Superset's docs and most tutorials
reach for, and on this instance it would hand every anonymous visitor on the internet:

    can_write on Chart · can_write on Dashboard · can_delete_embedded on Dashboard ·
    can_add / can_edit / can_delete on UserRegistrationsRestAPI · can_write on Theme

Checked, not assumed - that is a real subset of Gamma's 95 permissions. A stranger could create,
edit and delete dashboards, and register users. For a service Phase 12 puts on the internet, the
public role has to be built from nothing and justified line by line, which is what this does.

**The uncomfortable part: viewing a dashboard with working filters needs some WRITE permission.**
Superset stores a visitor's filter selections server-side and hands back a key, so
`can_write on DashboardFilterStateRestApi` is required for the done-when ("filters working") to be
true at all. It writes only transient filter state keyed to that visitor's own session - it cannot
touch a chart, a dashboard or any data. That narrow exception is listed explicitly below rather
than waved through as part of a bundle.

Idempotent: the role's permissions are set to exactly this list on every run, so anything granted
by hand in the UI is removed again.
"""

# Read-only permissions a dashboard viewer genuinely needs.
VIEWER_PERMISSIONS = [
    # the dashboard itself, its charts, and the datasets behind them
    ("can_read", "Dashboard"),
    ("can_read", "Chart"),
    ("can_read", "Dataset"),
    ("can_dashboard", "Superset"),
    # Running a chart's query - what fills the charts with numbers - needs no permission of its
    # own: the /api/v1/chart/data endpoint is guarded by `can_read on Chart` above. There is no
    # `can_read on ChartDataRestApi` in this build; the first version of this list invented it,
    # and the script reported it as NOT FOUND rather than silently skipping it.
    ("can_fetch_datasource_metadata", "Superset"),
    # the chrome: menus, translations, themes, and the CSRF token every POST needs
    ("can_get", "MenuApi"),
    ("can_read", "SecurityRestApi"),
    ("can_read", "Theme"),
    ("can_language_pack", "Superset"),
    ("can_log", "Superset"),
    # Found running a real embedded dashboard in a real browser for the first time (Phase 11 step
    # 6): the embedded app's own bootstrap calls GET /api/v1/me/roles/ before it renders anything,
    # and without this the whole embed fails with Superset's generic "Something went wrong with
    # embedded authentication" - a 403 on a request this list never anticipated, because nothing
    # before step 6 ever loaded the embed in an actual browser to find it.
    ("can_read", "CurrentUserRestApi"),
    # reading back the filter state and permalinks created below
    ("can_read", "DashboardFilterStateRestApi"),
    ("can_read", "DashboardPermalinkRestApi"),
]

# The narrow write exceptions, each one needed for a viewer to interact at all.
INTERACTION_PERMISSIONS = [
    # Filter selections are stored server-side under a key. Without this, a visitor cannot change
    # a filter - which is exactly what Phase 6's done-when requires to work.
    ("can_write", "DashboardFilterStateRestApi"),
    # Lets a visitor copy a link that reopens the dashboard in the state they were looking at.
    ("can_write", "DashboardPermalinkRestApi"),
]

# Never granted to anonymous visitors, and named here so the refusal is on the record:
#   can_write on Chart / Dashboard      - a stranger editing the published dashboards
#   can_delete_embedded on Dashboard    - a stranger breaking the Phase 11 embedding
#   can_sqllab / can_sqllab_history     - arbitrary SQL against the warehouse
#   can_explore / can_explore_json      - building new charts on any dataset
#   can_csv / can_export on *           - bulk download of the archive from the dashboard
#   can_add/edit/delete on UserRegistrationsRestAPI - self-registration
#   can_grant_guest_token               - minting embedding tokens (Phase 9 does that server-side)
# `can_csv` is arguably harmless public-interest data, but ADR 0003 and docs/permissions.md say
# CDSCO data is not republished in bulk until permission is recorded, so it stays off.

ROLE_NAME = "Public"
GOLD_DATASET_PREFIXES = ("mart_", "dim_", "fact_")


def main() -> None:
    from superset.app import create_app

    app = create_app()
    with app.app_context():
        from superset import db
        from superset.connectors.sqla.models import SqlaTable
        from superset.extensions import security_manager as sm

        session = db.session
        role = sm.find_role(ROLE_NAME)
        if role is None:
            role = sm.add_role(ROLE_NAME)

        wanted = []
        missing = []
        for permission, view in VIEWER_PERMISSIONS + INTERACTION_PERMISSIONS:
            found = sm.find_permission_view_menu(permission, view)
            if found is None:
                missing.append(f"{permission} on {view}")
            else:
                wanted.append(found)

        # Datasource access, one per gold dataset: this is the permission that decides WHICH data a
        # role may query. Granting it per dataset (rather than "all datasource access") means a
        # dataset added later is invisible to the public until someone says otherwise.
        datasets = session.query(SqlaTable).all()
        for dataset in datasets:
            if not dataset.table_name.startswith(GOLD_DATASET_PREFIXES):
                continue
            found = sm.find_permission_view_menu("datasource_access", dataset.get_perm())
            if found is not None:
                wanted.append(found)

        # Set the role to exactly this list: remove anything else it has picked up.
        current = set(role.permissions)
        target = set(wanted)
        for extra in current - target:
            sm.del_permission_role(role, extra)
        for addition in target - current:
            sm.add_permission_role(role, addition)
        session.commit()

        print(f"{ROLE_NAME} role now has {len(role.permissions)} permissions:")
        for permission in sorted(str(p) for p in role.permissions):
            print(f"  {permission}")
        if missing:
            print("\nNOT FOUND in this Superset build (check the names):")
            for name in missing:
                print(f"  {name}")
        removed = len(current - target)
        if removed:
            print(f"\nremoved {removed} permission(s) that were not on the list")


if __name__ == "__main__":
    main()
