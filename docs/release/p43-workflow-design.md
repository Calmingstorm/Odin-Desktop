# P4.3 workflow preparation, not release authorization

This scratch design is for parent adoption only after the notice is committed,
#24 is merged and the parent has merged current main. #24 was inspected read-only
at `2becee34d9308fe9b43a18d647f471020a5428ed`; GitHub subsequently reported merge
`5ba8d6dfcacce9eff823af2596290bc417897e0e`, 2026-10-06 02:10:18 UTC.
No workflow is activated by this document. No app or engine version is bumped.

## Shared entrypoint

`node scripts/release/rehearse.mjs --build=true --output=/absolute/fresh/evidence
--source=<40-hex-checkout-SHA> --workflow-sha=<40-hex-workflow-SHA>
--run-id=<positive-run-number>` is the future workflow's candidate entrypoint.
For a tag candidate, append `--tag=v0.1.0`. `--build=false` scans existing local
candidates but is not proof of a fresh workflow build. Local runs must clearly
label run IDs/workflow SHAs as local rehearsal identifiers, not fabricate Actions
provenance. Use a fresh isolated checkout, Node 22+, Python 3.12+ and P4.1's pinned
native prerequisites. Parent may reuse the reviewed packaging cache via
`ODIN_PACKAGING_CACHE`, but must serialize cache writers.

The Node wrapper uses an allowlisted build environment and disposable HOME,
dropping tokens, credential configuration, SSH agent, display/session variables
and NODE_OPTIONS. `npm ci --ignore-scripts`, pinned Electron provisioning and
`npm run package:candidate` produce both formats with P4.1's `--publish never`.
This is not a filesystem sandbox against arbitrary malicious build scripts: run
only reviewed first-party commits under a dedicated nonprivileged runner account
without host credential access, never the owner or live-service account.

The Python helper validates exact nonempty CHANGELOG section, npm root/lock
versions, tag, dpkg identity/version/architecture, ASAR-embedded app version,
bundle product version/source/lock provenance, finalized manifests identical
across formats, sizes and SHA-256s. It reuses P4.1's `qualify.scan_package` for
whole extracted trees and nested ASAR credential signatures, without executing
the application, qualification probes or installer. `extract_appimage` uses
unsquashfs and does not execute the AppImage runtime. Signature scanning is not
universal secret-absence proof. Neither this scan nor a valid URL establishes
native qualification, licensing closure or acceptance.

Output contains exactly the two unrenamed packages, curated `release-notes.md`
and `candidate-receipt.json`. Installer names match the actual target mappings:
`odin-desktop-0.1.0-candidate-amd64.deb` and
`odin-desktop-0.1.0-candidate-x86_64.AppImage`. The manifest remains an unsigned
inventory, never an update feed or trust anchor.

## Intended workflow control plane

After dependency/order confirmation, add `.github/workflows/release.yml`:

1. `workflow_dispatch` defaults `mode` to `dry-run`; other explicit choices are
   `retain-candidate` and `publish-approved`. `push.tags: [v*]` builds a candidate
   and never publishes. Optional reviewed internal PR dry-run may be added later;
   do not allow untrusted fork PR code on persistent self-hosted runners.
2. Every job uses `[self-hosted, odin-desktop-ci]`, minimal permissions and pinned
   reviewed Action commit IDs. Checkout uses `persist-credentials: false`, no
   submodules and full history/tag verification. Pin Node toolchain. Use fresh
   per-run checkout paths and job concurrency; never reuse stale candidates.
3. Build job (`contents: read`) runs helper tests, app `npm run check`, fixture
   smoke, real-core tests/smoke and a11y in the prescribed hard-isolated labs.
   It invokes the exact shared entrypoint. No `GH_TOKEN` or `GITHUB_TOKEN` is
   explicitly passed to build commands. Upload no artifacts in dry-run, including
   `actions/upload-artifact`; print receipt/hash provenance to the job summary.
   A dry-run checks the publication-denied path and stops.
4. An explicitly authorized retained candidate or version-tag candidate may store
   the exact output directory with `actions/upload-artifact` in Actions storage,
   not a GitHub Release. Hash/digest of the uploaded artifact and receipt, run ID,
   source commit and workflow commit are recorded in the summary. Retention must
   cover P4.5/P4.6. Tag creation itself is separately Aaron-authorized. No tag
   alone can grant the publish job contents-write permission.
5. `publish-approved` is a separate manual dispatch on trusted default-branch
   workflow code. Require `github.actor == 'Calmingstorm'`, candidate run ID,
   exact source SHA, workflow SHA, receipt SHA and full approval JSON. Approval
   repeats both filenames/size/hashes and explicit P4.5/P4.6 reviewed evidence
   references plus `action: publish-identical-candidate` and Aaron identity.
   Fetch the candidate run's metadata through the Actions API: repository,
   successful conclusion, candidate workflow path/ID, event, source SHA and
   recorded workflow SHA must match. Reject arbitrary run IDs/workflows, PR
   provenance, expired/replaced artifacts and fork origins. Download the stored
   artifact by immutable ID and verify its Actions artifact digest plus receipt
   hash and all file hashes against Aaron's dispatch inputs. Never rebuild.
6. A read-only verification job emits exact verified SHA/hashes and evidence for
   review **before** the publication job's environment gate. The publication job
   uses protected environment `odin-desktop-release`, restricted to default main
   and required reviewer Aaron. Disable admin bypass where supported. Environment
   configuration is out-of-repository and must be audited; YAML alone cannot
   require an actual reviewer or prove P4.5/P4.6 have passed. The helper checks URL
   shape only. Aaron's authenticated dispatch plus required environment review
   attests that those reviewed gates really approved these exact bytes.
7. Only after that review, publication job (`contents: write`, other scopes none)
   downloads the **same immutable artifact ID**, repeats digest/file validation,
   and resolves the intended tag recursively to its commit via authenticated
   GitHub API or a fetched exact tag. Require that commit equals receipt source.
   `gh --verify-tag` by itself checks existence, not SHA equality. Pass the trusted
   resolved source to `publication_plan`. Plan returns argv, never executes it.
   Only the final publish step receives `GH_TOKEN: ${{ github.token }}` and executes
   that argv, attaching the downloaded files and receipt unchanged. Fail if a
   release already exists; no clobber, replacement or retry-rebuild. Partial upload
   failure requires manual reconciliation, not an automatic second publication.
8. Verify release target and both attached asset digests after publication. Any
   mismatch is a failed publication requiring owner intervention, not success.
   Repository-native release asset SHA-256 evidence should be compared to receipt;
   if unavailable, download assets for hashing in the authorized publication job.

The protected environment review occurs after candidates exist, not a generic
approval preceding a new build. Rebuilding any package creates new hashes and
requires new affected acceptance/approval. Implementing this lane grants no
permission to push tags, publish releases, upload assets or waive legal/native
gates.

## Parent adoption and validation

- Cherry-pick the scratch helper/design commit only once dependencies/order are
  satisfied. Do not merge this scratch branch or overwrite the notice worktree.
- Add the workflow after notice completion, recheck actual P4.1 interfaces and
  register its publication environment before claiming it is operational.
- Python tests: run `python3 -B -m unittest discover -s scripts/release/tests -v`
  under the PID namespace in CONTRIBUTING. Node tests:
  `node --test scripts/release/tests/rehearse.test.mjs`.
- Parent runs the complete nonpublishing fresh-candidate rehearsal with the same
  entrypoint. This preparation did not build packages, dispatch a workflow or
  test real release publication. Unit fixture bytes are not installer evidence.
- Keep release evidence out of Git. No maintenance ledgers or engine files were
  changed by this preparation. Main product version stays `0.1.0`.
