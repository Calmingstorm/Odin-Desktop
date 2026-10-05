# D14 PDF first-use resource

Aaron chose automatic first-use PDF download on 2026-10-05. PyMuPDF remains the
optional `[pdf]` extra, not a production dependency. `pdf.py:stage_pdf` validates
the optional `uv.lock` wheel pin and copies only `pdf.lock.json` to
`resources/runtime/pdf.lock.json`. It performs no download and stages no wheel,
MuPDF shared objects, PyMuPDF packages or `COPYING` notice. Existing PDF payload
in a stage is rejected instead of silently incorporated.

The unchanged lock retains the original HTTPS URL, SHA-256, PyMuPDF 1.28.2
Linux x86-64 CPython abi3/manylinux 2.28 wheel name and license provenance.
The engine's shared `src.runtime.pdf_resources` resolver reads the immutable pin,
downloads and hash-checks the wheel, then installs it in the selected profile's
private writable data directory. It never modifies application resources.
Concurrent callers share the installation; offline/hash failures leave no usable
install and the next call retries. PDF attachments, knowledge imports and
`analyze_pdf` all use that path. `analyze_pdf` remains offered before installation.

The package qualifier requires `--pdf-wheel <local-pinned-wheel.whl>`. The fixture
is SHA-256 verified and mounted read-only separately from the candidate in a
network-disabled namespace. The candidate starts without `fitz` or `pymupdf`;
only its resolver download transport is replaced with fixture copying. Its actual
verification/extraction and real extraction handler run against disposable user
state. The packaged runtime remains read-only, and a second resolution reuses the
install. No fixture or installed PDF bytes become part of either candidate.

Package/tree and ASAR checks reject PyMuPDF/MuPDF/legacy fitz payload paths,
including wheel, package, native library and license staging. This is checked on
actual extracted/installed candidate contents, not merely a dependency declaration.

PyMuPDF identifies itself as AGPL-3.0-or-later or commercially licensed.
**PyMuPDF/MuPDF is not distributed in these candidates.** Keeping its pinned
first-use download does not make a legal determination about all resulting
application use; final distribution licensing remains an owner/legal decision.
