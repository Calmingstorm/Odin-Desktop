# P4.3 release workflow implementation record

## Order and scope

Notice first: `6c3bc43e`. P4.1 PR #24 merged as `5ba8d6df`; this branch then
merged main as `ff8bb499` and adopted offline helpers as `4ea8e842`.
Product version stays `0.1.0`. This record authorizes no release, tag, repository
visibility change, environment change or installer use.

Implementation: `.github/workflows/release.yml`, `scripts/release/`. No app,
engine or inherited test corpus edits. Fixed repository:
`Calmingstorm/Odin-Desktop`. All jobs use `[self-hosted, odin-desktop-ci]`.
Persistent runners must execute reviewed first-party code as a dedicated
nonprivileged account without owner credentials or active graphical seat.
No fork or PR trigger is enabled.

## Production candidate behavior

- Manual dispatch defaults to `dry-run`, version `0.1.0`. Version must match
  existing npm root/lock metadata; CI never edits versions.
- `workflow_entry.py` invokes shared local/Actions `rehearse.mjs --build=true`.
  Allowlisted disposable HOME drops credential/session/SSH/Node configuration.
  Build: `npm ci --ignore-scripts`, pinned Electron provision,
  `npm run package:candidate`, P4.1 `--publish never`.
- Both real packages are extracted without executing installers. Exact curated
  CHANGELOG section, dpkg identity/version/architecture, embedded ASAR version,
  source/lock provenance, resource manifests, sizes, hashes and P4.1 credential
  signatures must pass. Unauthorized publication is tested denied. Signature
  scans are not universal secret-absence proof or licensing/native acceptance.
- Sanitized gates run helper tests, `npm run check` inside a PID namespace,
  fixture smoke, real-core tests/smoke and accessibility. Existing namespace and
  virtual-display entrypoints remain mandatory. Prerequisites: Node22,
  Python3.12, native packaging tools/libraries, Xvfb, gh, and noninteractive
  approved sudo namespace isolation. Missing isolation has no unsafe fallback.
- Dry-run uploads nothing, including no Actions artifact. Build modes never
  create tags or Releases. Aaron-only `retain-candidate`, or Aaron-originated
  exact-version tag push, may retain immutable Actions storage for 30 days.
  A tag is never publication authorization. Reruns are rejected; new candidates
  need new runs. Summaries show package/receipt hashes and retained ID/ZIP digest.

## Future publication: blocked until configured and accepted

Separate Aaron manual dispatch on main, never tag-triggered and never a rebuild.
Read-only verification precedes protected-environment review. Inputs identify
candidate run, immutable artifact ID/digest, source/workflow SHAs, receipt hash,
version and approval JSON. Candidate source/workflow and current trusted workflow
must be the same commit. Moving main requires a new candidate/affected approvals.
A caller-supplied workflow SHA is not independent API provenance.

Approval repeats exact package names/sizes/hashes, receipt, artifact ID/digest,
source/workflow/run IDs, Aaron identity, publication action, and reviewed P4.5
and P4.6 issue/PR evidence links. URL shape does not prove gate completion:
Aaron's authenticated dispatch and environment review attest to actual acceptance
of those exact bytes. API checks verify workflow/run/repository/job provenance,
safe exact ZIP membership and digest, receipt/files/approval, and recursively
resolve the existing version tag to the source commit. Existing Releases are
refused. Final step receives only Actions-scoped token and executes exact-file
publication argv once; attached asset identities/sizes/digests are checked.
Partial failure needs owner reconciliation, never clobber or automatic replay.

**External protection is not installed here.** Parent observed zero environments.
Helper audits `odin-desktop-release` before verification and again inside publish:
explicit admin-bypass prevention, only Aaron as required User reviewer, self-review
permitted for his dispatch, custom main-only branch policy. Missing/unreadable
protection or API fields fail closed. YAML `environment:` can auto-create an
unprotected environment and is not authority. Owner must separately configure
and audit it. Unsupported plan/API fields or token permissions deliberately keep
publication blocked. No real environment review or publication was exercised.

## Evidence and parent handoff

Targeted tests execute actual YAML conditions and candidate shell entry with a
fake builder; offline/API fixtures cover future verification and denied paths.
They are not an Actions run or real installer/native proof. `actionlint` validates
YAML with only the exact configured custom runner label.

**Parent evidence pending:** parent owns fresh final app/packaging/short gates and
real two-format nonpublishing shared-entrypoint rehearsal at the final commit.
Fill external evidence path, exact provenance, package/receipt hashes, gate results
and honest local-vs-Actions distinction in PR/evidence handoff. Do not fabricate
Actions run IDs for local rehearsal. New dispatch may be unavailable before
default-branch registration. P4.5 qualification, P4.6 live acceptance, licensing
closure, actual approval and release upload are not completed by this lane.
