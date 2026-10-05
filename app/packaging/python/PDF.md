# D14 PDF resource

`pdf.py:stage_pdf(bundle_root, cache_dir)` stages PDF evidence from the already
installed, locked production runtime. It deliberately does not download or
install wheels: the Python runtime stage owns dependency resolution and makes
PyMuPDF 1.28.2 available. The wheel must be present in the content-addressed
`python-runtime/wheelhouse` cache and match both `uv.lock` and
`pdf.lock.json`. The supported binary here is Linux x86-64, CPython 3.12,
manylinux 2.28 x86-64 (the wheel uses CPython's abi3 tag).

The returned metadata inventories the wheel provenance and digest, MuPDF
native shared objects/digests, and the packaged `COPYING` license notice. It
also runs a subprocess with isolated Python mode and unusable HTTP(S) proxy
addresses; that subprocess creates a one-page PDF in memory, opens it using
the staged `fitz.open(stream=..., filetype="pdf")` engine API and extracts
text. A second isolated subprocess calls the real
`src.tools.handlers.files_docs.FilesDocsTools._handle_analyze_pdf` with a
stubbed local host-byte reader and asserts the handler's page-labelled result.
This proves both native PDF support and the engine's actual extraction path
can execute without a feature download. It does not prove package-level offline
qualification by itself.

**License review required before distribution.** PyMuPDF identifies itself as
dual licensed under GNU AGPL-3.0 or the Artifex Commercial License. The wheel
contains a short `COPYING` notice, not the full license texts. The project must
obtain legal review of applicable AGPL obligations or confirm the required
commercial license before shipping; this staging code does not resolve that
choice. The native libraries are bundled inside the PyMuPDF wheel, so their
third-party notices and license coverage also need review.
