"""Export every dashboard, chart and dataset from Superset into the repo as YAML.

Phase 6 step 5. Until now the dashboards existed in two places: the build scripts that create them,
and Superset's own database. Neither is a deployable artifact - the scripts need a running Superset
with the right ids, and the database is not in git.

Superset's export bundle is both: it is the format `superset import-dashboards` reads, so Phase 12
can recreate the dashboards on the server from the repo, and it is plain YAML, so a change to a
chart shows up as a reviewable diff.

**Secrets:** a bundle contains the database connection, and Superset writes the password as a
placeholder rather than the real value. This script checks that before writing anything to disk and
refuses if a real password appears - the one thing that must never land in git.

Run from the repo root, with the stack up and `.env` loaded:
    set -a && . ./.env && set +a && python3 infra/superset/export_assets.py
"""

import io
import os
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from superset_api import from_env  # noqa: E402

ASSETS = Path(__file__).parent / "assets"


def main() -> int:
    superset = from_env()

    dashboards = superset.get("/api/v1/dashboard/?q=(page_size:100)")["result"]
    if not dashboards:
        print("no dashboards to export")
        return 1
    ids = sorted(dashboard["id"] for dashboard in dashboards)
    print(f"exporting {len(ids)} dashboard(s): {[d['dashboard_title'] for d in dashboards]}")

    # The export endpoint answers with a zip, not JSON, so it bypasses the usual client.
    import urllib.parse
    import urllib.request

    query = urllib.parse.quote(f"!({','.join(str(i) for i in ids)})")
    request = urllib.request.Request(  # noqa: S310 - fixed localhost URL
        f"{superset.base_url}/api/v1/dashboard/export/?q={query}",
        headers={"Authorization": f"Bearer {superset._token}"},  # noqa: SLF001
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        payload = response.read()

    bundle = zipfile.ZipFile(io.BytesIO(payload))
    names = [name for name in bundle.namelist() if name.endswith((".yaml", ".yml"))]

    # Refuse to write if a real credential is in the bundle. The reader password is the only secret
    # Superset knows, so that is what is searched for.
    reader_password = os.environ.get("SUPERSET_READER_PASSWORD", "")
    if reader_password:
        for name in names:
            if reader_password.encode() in bundle.read(name):
                print(f"REFUSING to write: {name} contains the real database password")
                return 1
    print("checked: no real credentials in the bundle")

    if ASSETS.exists():
        shutil.rmtree(ASSETS)
    ASSETS.mkdir(parents=True)
    for name in names:
        # Drop the export's timestamped top directory so a re-export produces a clean diff rather
        # than a new folder every time.
        relative = Path(*Path(name).parts[1:])
        target = ASSETS / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bundle.read(name))

    written = sorted(path.relative_to(ASSETS).as_posix() for path in ASSETS.rglob("*.yaml"))
    print(f"wrote {len(written)} file(s) to {ASSETS.relative_to(Path.cwd())}:")
    for name in written:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
