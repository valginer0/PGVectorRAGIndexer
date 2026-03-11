---
description: How to release a new version of PGVectorRAGIndexer
---
# Release Process for PGVectorRAGIndexer

When the user asks to release a new version of PGVectorRAGIndexer, follow these steps exactly.
The user expects YOU (the AI agent) to perform the entire end-to-end process, including downloading the unsigned installer, waiting for them to sign it, and uploading it back to GitHub. Do not just print instructions for the user.

## Step 1: Prepare and Run Release Script
1. Ensure all changes are committed (the git tree must be clean).
2. Ask the user if this is a `patch`, `minor`, or `major` release based on the changes made.
3. Run the release script from the root directory:
   ```bash
   ./release.sh -y <bump_type>
   ```
   *Note: If GitHub Container Registry (ghcr.io) authentication fails at the end, use `gh auth refresh -h github.com -s write:packages` and `gh auth token | docker login ghcr.io -u valginer0 --password-stdin` to authenticate via the device code flow, then re-run the release script if necessary.*
4. Wait for the test suite, Docker build, tagging, and pushing to complete successfully.

## Step 2: Download Unsigned MSI
1. The release script triggers a GitHub Actions workflow called "Build Windows Installer". Monitor its status:
   ```bash
   gh run list --workflow "Build Windows Installer" --json databaseId,name,status,conclusion,headBranch | head -n 10
   ```
2. Wait for the workflow for the new tag (e.g., `v2.9.0`) to complete with `conclusion: success`.
3. Download the artifact directly to the user's Windows filesystem via the WSL mount point. **The user expects this specific path**:
   ```bash
   // turbo-all
   mkdir -p /mnt/c/Users/v_ale/Desktop/ToSign/PGVectorRAGIndexer-unsigned
   rm -f /mnt/c/Users/v_ale/Desktop/ToSign/PGVectorRAGIndexer-unsigned/PGVectorRAGIndexer.msi
   gh run download <run-id> --name PGVectorRAGIndexer.msi --dir /mnt/c/Users/v_ale/Desktop/ToSign/PGVectorRAGIndexer-unsigned
   ```

## Step 3: Wait for User Signature
1. Notify the user using the `notify_user` tool with `BlockedOnUser: true`.
2. Inform them: "The unsigned MSI has been downloaded to `C:\Users\v_ale\Desktop\ToSign\PGVectorRAGIndexer-unsigned\PGVectorRAGIndexer.msi`. Please sign it using `signtool.exe` and let me know when you are done."
3. Wait for the user to confirm they have signed it.

## Step 4: Upload Signed MSI to GitHub Release
1. Once the user confirms the signature is complete, upload the signed MSI from their Windows filesystem directly to the GitHub Release.
   ```bash
   // turbo
   gh release upload <tag> /mnt/c/Users/v_ale/Desktop/ToSign/PGVectorRAGIndexer-unsigned/PGVectorRAGIndexer.msi --clobber
   ```
2. Notify the user that the release is complete. Note that `release.sh` provides convenience automation to push the version bump to the `PGVectorRAGIndexerWebsite` repository, but this assumes the environment is set up correctly (e.g. at `../PGVectorRAGIndexerWebsite` and on `main` branch). If that automation is skipped or fails, you may still need to deploy the website manually.
