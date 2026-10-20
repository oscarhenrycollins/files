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

Checks: `python3 -m unittest discover -s tests -v` (PyYAML required),
`python3 mcp/inline.py --check`, and `wam check .`.

