# Export and delete a workspace

Open **Setup → Export and delete**. Only owners can use this page (in a firm, partners can also
export). You are asked to sign in again if your last sign-in is not recent.

## Export everything
Select **Download the export**. You get one ZIP file with:
- `tables/`: one file per kind of record, one record per line (JSON);
- `documents/`: the files you uploaded;
- `members.jsonl`: the people in the workspace;
- `manifest.json`: for every file, how many records it holds and its SHA-256 hash, so you can
  check that the export is complete and unchanged.

The file holds all your data. Keep it somewhere safe.

## Delete the workspace
Deleting removes every record and document of the workspace for good. It takes two steps:

1. Select **Start deleting this workspace**. Nothing is deleted yet.
2. Type the workspace's name exactly and select **Confirm the deletion**.

After you confirm, the workspace is deleted **30 days later**. Until then:
- you can keep working, and every page shows the date;
- any owner can select **Keep this workspace** to stop the deletion.

After the 30 days the deletion cannot be undone. Download an export first. Backups made before
the deletion expire on their own schedule (up to one year).
