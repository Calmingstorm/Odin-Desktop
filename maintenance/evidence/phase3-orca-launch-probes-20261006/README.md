# Focused native launch evidence, not full Orca qualification

These are the one-launch probes Aaron required after the common Wayland
launch/focus failures. Originals are preserved at
`/home/odin/reviews/p34-focused-{kde,gnome}-v13/`.

- KDE: one native Wayland Electron launch with logging enabled. Actual stderr,
  AT-SPI snapshot, Message-entry speech and inspected full guest screenshot.
- GNOME: plain native GTK entry/button speech first, then one native Wayland
  Electron launch with actual Message-entry speech and inspected guest image.

Both probe-result files report success; runtime sandbox/context isolation
remained enabled and node integration disabled. They do not claim the full
seven task groups passed, nor native attachment selection/Save.

The proofs truthfully record dirty working-source builds at their base Git
SHA. Their actual source/runtime file digests, guest comparison and artifact
SHA-256 are retained in `proof.json.gz`; no clean-commit build is inferred.
`orca-debug.log.gz` preserves the complete native debug output, including
non-speech AT-SPI diagnostics. Only anchored `SPEECH OUTPUT` records support
the speech verdicts. No real credential was used; diagnostic text is not
screen-reader speech or target authority.

Compression uses `gzip -n`: decompression restores the exact original UTF-8
bytes. `SHA256SUMS` checks the checked-in compressed and uncompressed files,
excluding itself. The guest proof contains original evidence hashes, and the
host proof verifies pulled bytes. Runtime/dependency archives were not added
to Git.

Visual inspection: KDE and GNOME screenshots show the actual rendered Odin
window with Message focus outline, not an overview or a CDP-only document.
GNOME's GTK screenshot shows its probe entry and button in a visible native
window. These pixels are independent visual evidence, not a speech verdict.
