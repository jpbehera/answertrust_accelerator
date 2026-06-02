# Fabric data plane — Git-sync workflow

This folder is the **Git-synced root** for the AnswerTrust Fabric data plane. A Fabric
workspace is connected to this repository via **native Git integration**, so the module
notebooks and the orchestration pipeline live here in Fabric's Git item format and sync
both ways between GitHub and the workspace.

> The Azure **control plane** (App Insights, Log Analytics, Sentinel, RBAC under
> [`../infra`](../infra)) is **not** part of Fabric Git. It deploys separately via
> `azd up` (see [`../docs/SETUP_GUIDE.md`](../docs/SETUP_GUIDE.md)). The postprovision
> REST push in [`../azure.yaml`](../azure.yaml) is disabled so it doesn't conflict with
> the Git-synced items in this folder.

---

## What lives here

Once the workspace has committed, this folder contains one subfolder per Fabric item,
each in Fabric's Git format (a `.platform` descriptor + content):

```
fabric/
  <Notebook name>.Notebook/        # e.g. 00_Prerequisites_Check.Notebook/
    .platform                      # item type, displayName, logicalId
    notebook-content.py            # notebook source (NOT raw .ipynb)
  AnswerTrust_Deploy_Pipeline.DataPipeline/
    .platform
    pipeline-content.json
```

> Raw `.ipynb` files (such as those under [`../modules`](../modules)) are **not** in
> Fabric Git format and are ignored by Fabric sync. They remain the human-readable
> source of truth; the canonical Fabric format here is what Fabric reads.

---

## One-time setup (per workspace)

1. **Branch** — connect Fabric to a dedicated branch, not `main`:
   ```bash
   git checkout -b fabric/dev
   git push -u origin fabric/dev
   ```
2. **Connect** — in the Fabric portal: **Workspace settings → Git integration**
   - Provider: **GitHub** → authorize
   - Repository: `answertrust_accelerator`
   - Branch: `fabric/dev`
   - **Git folder: `/fabric`** (this folder)
   - **Connect**, then **Sync**.
3. **Seed the items** (first time only) — get the notebooks + pipeline into the
   workspace, then let Fabric write the canonical Git format back:
   - Push via the existing script (fastest):
     ```bash
     az login
     export FABRIC_WORKSPACE_ID="<your-workspace-guid>"
     bash ../scripts/deploy-fabric-pipeline.sh
     ```
     …or **New → Import** each notebook / the pipeline in the portal.
   - In the workspace **Source control** panel → **Commit all**. Fabric writes the
     `*.Notebook/` and `*.DataPipeline/` folders into `/fabric` on `fabric/dev`.
   - Pull locally: `git pull` — the repo now holds Fabric-native items.

---

## Day-to-day workflow

### Edit in Fabric → land in Git
1. Make changes in the Fabric workspace (notebook/pipeline edits).
2. Open the **Source control** panel → review diffs → **Commit** (commits to `fabric/dev`).
3. Locally: `git pull`.
4. Open a PR `fabric/dev → main` for review/promotion.

### Edit locally → land in Fabric
1. Edit the item files under `fabric/` (mind the `.platform` + `notebook-content.py`
   format), commit, and `git push` to `fabric/dev`.
2. In Fabric **Source control** → **Update** to pull the changes into the workspace.

### Golden rules
- **One direction at a time.** Don't edit the same item in Fabric and locally before
  syncing — resolve/commit one side first to avoid conflicts.
- **Never hand-edit `logicalId`** in a `.platform` file. Fabric uses it to map repo
  items to workspace items; changing it breaks the link.
- **Keep `main` clean.** Treat `fabric/dev` as the integration branch; promote to `main`
  via PR.
- **Secrets stay out of Git.** Item definitions are plaintext; use Key Vault / workspace
  connections for credentials.

---

## Running the data plane

After items are synced into the workspace, run the notebooks in order (`00 → 10`) or
trigger **AnswerTrust_Deploy_Pipeline**, setting each notebook's `parameters` cell (or the
pipeline parameters) per the table in [`../docs/SETUP_GUIDE.md`](../docs/SETUP_GUIDE.md).
