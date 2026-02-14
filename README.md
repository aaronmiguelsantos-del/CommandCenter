# Aaron Command Center (v0.1)

A modular command-center repo designed for agentic work:
- clean module boundaries
- one-command run
- safe local state
- exportable bundles

## Run
```bash
python3 -m app.main help
python3 -m app.main list
python3 -m app.main run creativity status
python3 -m app.main run exports bundle --name v0_1_smoke
```

## Notes
- No external services.
- Modules are placeholders for v0.1.

## Create a shareable zip
```bash
./scripts/package_zip.sh
```
This creates `dist/aaron-command-center-v0.1.zip` with the full project (excluding `.git`, virtualenv, caches, and existing zip artifacts).

## Troubleshooting GitHub sync
If `git status` says clean but `ls` only shows `README.md`, your GitHub repo does not yet contain the scaffold files.

Use this flow to import the scaffold into your clone and push it:

```bash
# from your machine, with both folders present
# source folder has app/, scripts/, tests/
# destination is your git clone
rsync -av --exclude '.git' /path/to/source/ /path/to/CommandCenter/
cd /path/to/CommandCenter
git add .
git commit -m "Import Aaron Command Center v0.1 scaffold"
git push origin main
```

After that, run:
```bash
./scripts/package_zip.sh
```
