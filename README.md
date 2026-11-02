# Files

Your own cloud folder for videos, documents and folders, shared by every Wizard app.

A [Wizard app](https://www.aiwizards.com/wizard-apps): install it from the Wizard Apps screen, or with the Wizard App Manager on any box running stock [Runtipi](https://runtipi.io).

- `wizard.md`: what the app is and what it gives the agent (spec: wizard.md v0.2).
- `runtipi/`: stock Runtipi `config.json` and `docker-compose.yml`.

- `.github/workflows/publish.yml`: every push to `main` re-publishes to the index at apps.aiwizards.com.

## Wizard hosting

The view lives at `/files/` (File Browser's own folder route is therefore
`/files/files/<path>`). `FB_BASEURL=/files` applies to both new and existing
databases; the engine healthcheck follows the same prefix. `/mcp` remains
box-only and unprefixed. Existing files, database mounts and permissions are
preserved; no recursive permission change is added.

The matching App Manager publishes the view on the shell's private same-origin
`/files/` route. That makes the existing Store **Open** action available without
loosening frame security. Files is already a required bootstrap default. A
Wizard OS release must pin this recipe and the matching manager together before
stable new installs receive the complete fix; a repository merge/index refresh
alone does not advance the OS release pointer.

## Browser boundary (draft, default-off)

Approved separate-origin exception (wizard-os #385, 2 Nov 2026). With the
browser boundary on (`WIZARD_BROWSER_BOUNDARY=1`, written by the App Manager
together with `WIZARD_OWN_HOSTS`), File Browser runs on its **own origin** (its
own HTTPS port) and opens only as its own tab; Wizard never frames it. The front
then refuses, before File Browser sees them: frame/embed requests, opaque or
foreign `Origin`, cross-site and same-site requests (other Wizard addresses on
the same host are same-site) other than a plain top-level GET navigation, and,
with `WIZARD_OWN_HOSTS`, any request whose `Host` is not Files' own address (an
old `/files/` route on the Wizard address). Replies carry `X-Frame-Options:
DENY`, `frame-ancestors 'none'`, CORP and COOP `same-origin`. Apps on this box
and the owner gate are unchanged. Off, nothing changes.

Residual (not fixed here): File Browser's own `auth` cookie is host-scoped, so
other listeners on the same host receive it. A box-local caller gains nothing
from it (File Browser's noauth login already answers box-local callers), and a
browser request carrying it from another origin is refused above.

Checks: `python3 -m unittest discover -s tests -v` (PyYAML required),
`python3 mcp/inline.py --check`, and `wam check .`.

