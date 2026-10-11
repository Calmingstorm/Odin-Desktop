# Windows 4a payload consumers and supplier evidence

These are private, disposable phase-4 candidate inputs, not a production-support
or completed native-qualification claim. Locks contain exact URLs, sizes, SHA-256,
licenses and provenance. Pins were measured from downloaded bytes; cache reuse
also checks size and SHA-256.

| Input | Exact size | SHA-256 |
| --- | ---: | --- |
| Chrome Headless Shell 153.0.8010.12 win64 | 120200717 | `7aec872f3090e639c4237467624ea863c20fe2878914c93a6556bdbb52aa6c4c` |
| Playwright 1.63.0 win_amd64 wheel | 38606082 | `2f9a707a6c6c91157ed77bff2b8caeb04b3c8d46e70d585fc134298cbe4b5cc6` |
| Microsoft OpenSSH 10.0.0.0p2-Preview Win64 zip | 5704583 | `23f50f3458c4c5d0b12217c6a5ddfde0137210a30fa870e98b29827f7b43aba5` |
| Official curl 8.22.0_3 win64-mingw zip | 8688824 | `f38b0ac2e3a280fd414b607c874a21e6dd4d1ed0e2ae622afbf0020917446561` |
| curl's CA bundle from that zip | 188900 | `1fdcf2a55c9806c4c1e8391cb283871ee3b209d68a2879ce4c0898d949de2545` |

## Assembly and consumers

- `chromium.stage_chromium(runtime, cache)` selects the Windows lock natively,
  verifies the wheel against uv.lock and browsers.json/Node bytes, and stages all
  290 browser files. The data/DLL closure has a deterministic inventory pin.
- `tools.stage_tools(resources, cache)` atomically stages a fresh resources/tools
  tree. It preflights the entire archives under Windows semantics, selects only
  the locked client closure, checks its deterministic inventory pin, recursively
  audits PE imports, and never runs an installer or service script. Existing tools
  destinations are refused rather than merged.
- ODIN_DESKTOP_BUNDLE_ROOT names resources/runtime, as the existing launcher does.
  Tools are its sibling resources/tools. A bundled interpreter's sys.prefix at
  resources/runtime/python independently proves that location; an environment
  mismatch is refused, and absent environment does not trigger System32 fallback.
  Source execution retains existing OS-copy behavior.
- Browser resolution uses only the exact headless-shell .exe under runtime. The
  Windows Playwright consumer requires install-relative node.exe and refuses
  PLAYWRIGHT_NODEJS_PATH, NODE_OPTIONS and NODE_PATH overrides. Existing launch
  policy keeps chromium_sandbox=True, never --no-sandbox.
- Models/tokenizer use existing Linux byte pins with no second Windows set.
  Windows PDF staging copies the existing pdf.lock.win_amd64.json as
  runtime/pdf.lock.json; PDF remains verified optional first-use download.

## OpenSSH status and limits

Microsoft's release explicitly says **preview-release (non-production ready)**
even though GitHub reports prerelease:false. Only ssh, ssh-keygen, libcrypto.dll,
LICENSE and NOTICE ship. No server, agent, services or supplier scripts ship.
Hardware-key/PKCS11 helpers are not offered by this client-only closure. Resolve
support acceptance or supplier replacement before phase-5 publication. Native
publisher signature qualification is pending.

## curl supplier and TLS policy

Downloaded digest agrees with curl's official download page and versioned .zip.txt.
The official detached OpenSSH signature was successfully verified with
ssh-keygen -Y verify, using supplier allowed-signers pinned to curl-for-win commit
9d77e31e. Fingerprint, identity, signature URL/hash and trust-anchor URL/hash are
recorded in the lock. This authenticates against the reviewed supplier HTTPS
trust anchor, not an independently verified human identity. Windows code
signatures are reproducibly self-signed, not Windows-trusted publisher evidence.

The supplier build says static LibreSSL 4.3.3. Native curl --version must verify
that backend. Both real local routes, windows_helpers.probe (http_probe) and
windows_validate.windows_probe (validate_action HTTP), use:

`curl.exe --disable --ca-native`

That trusts the Windows certificate store, where administrators add enterprise
roots, as Linux's curl trusts the system store. The CA bundle the build ships
beside curl.exe is trusted as well. CURL_CA_BUNDLE, SSL_CERT_FILE and
SSL_CERT_DIR keep curl's own meaning, as on Linux. There's no curlrc, insecure
retry or CA download fallback. Explicit caller verify_ssl=false remains separate
behavior. Native qualification must show trusted HTTPS succeeding and an
untrusted certificate and a hostname mismatch refused through both routes. Do
not mutate the real user's certificate store to qualify this policy.

## Observed checks and remaining evidence

- Focused tests: 88 passed and 9 subtests passed, including Linux browser/PDF
  regressions, Windows consumer strict refusals, driver overrides, transaction
  cleanup, pin requirements and search byte pins. Owned files pass Ruff.
- Actual inputs assembled into private temporary trees with Windows branch
  selected on Linux. Browser: 290 files, 283217434 bytes; tools: exact selected
  clients/notices/CA closure. No native binary executed.
- Cross-host static audit passed all five browser PE files, Playwright Node,
  ssh/ssh-keygen/libcrypto.dll, and curl.exe. Browser includes normal/delay imports,
  52 explicit OS modules. This proves static closure, not native OS availability.
- Still required: hosted Windows stage/load/real browser, offline inference,
  PDF first use and TLS routes; Legion disposable strict-host-key SSH success,
  incorrect-host-key refusal, private-key ACL behavior, standard-user clean-machine
  loading and native supplier signature checks. Windows N without Media Feature
  Pack is not qualified by the non-N DLL baseline.
