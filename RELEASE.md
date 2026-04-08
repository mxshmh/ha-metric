# Release Checklist (Beta)

## 1) Create repository

- Create a new GitHub repository, e.g. `ha-metric`.
- Upload this folder content as repository root.

## 2) Verify structure

Repository root should contain:
- `custom_components/hametric/*`
- `README.md`
- `CHANGELOG.md`
- `LICENSE`
- `hacs.json`

## 3) Tag beta release

- Create tag: `v0.1.0-beta.1`
- Publish GitHub Release with short notes from `CHANGELOG.md`.

## 4) HACS test

- Add repo as HACS custom repository (Integration).
- Install on a clean HA instance.
- Verify setup/options/reload and entity creation/removal.

## 5) Public beta

- Mark repository as public.
- Mention clearly this is a beta and invite issue reports.
