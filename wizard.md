---
wizard: 0.2
id: files
name: Files
type: view
version: 2.63.23
summary: Your own cloud folder for videos, documents and folders, shared by every Wizard app.
license: WTFPL
source: https://github.com/minhyeong112/files
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
view:
  path: /
  port: 8794
provides: [files]
needs: [files]
---

# Files

Your own cloud folder for videos, documents and folders, shared by every Wizard app.
