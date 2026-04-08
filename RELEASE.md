# Release Checklist

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

## 3) Tag release

- Create tag: `v1.0.0`
- Publish GitHub Release with short notes from `CHANGELOG.md`.

## 4) HACS test

- Add repo as HACS custom repository (Integration).
- Install on a clean HA instance.
- Verify setup/options/reload and entity creation/removal.

## 5) Public release

- Mark repository as public.
- Invite issue reports for ongoing improvements.
