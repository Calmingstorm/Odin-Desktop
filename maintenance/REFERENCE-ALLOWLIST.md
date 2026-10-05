# Narrow reference exceptions for Phase 1 review

Removed features are not runtime integrations. This is not a blanket `Discord` or
`src/discord` exemption. The AST source/wheel gate rejects third-party transport
imports, and the catalog tests reject removed tool registrations and schemas.

| Reference | Disposition and limits |
|---|---|
| `maintenance/odin-v4.13.0.tar.gz`, `UPSTREAM-LICENSE`, baseline manifests and patches | Immutable source/legal provenance, not installed wheel contents. |
| Approved design/discussion/work documents | Historical evidence, not runtime prompt context. |
| `src/discord/` paths and relative imports to retained neutral modules | Original module paths for exact upstream diffs. This never permits a gateway, social operation or `discord.py` import. |
| Retained upstream tests and native proof assets/scripts | Case/provenance fixtures. Phase 2, foundation-adaptation and safety/manual partitions are explicit. Not shipped as runtime source or authorized to run against an active desktop. |
| `src/llm/secret_scrubber.py` token-shaped recognition | Live credential protection. Pasted third-party tokens remain secrets; no transport capability is enabled. |
| Internal `CommandGovernor` baseline ABI and diagnostic `admin override` strings | Baseline classifier text/API is preserved per the work order. Desktop dispatch always passes `user_tier=None`, and a sealed owner context never enables this override. No tier CRUD, user grants or tier config is offered. Exact-action approval integration is unavailable pending Phase 2. This compatibility exception requires independent review, not an inferred wording approval. |
| Historical audit-log governor recognizers | Parse old/retained diagnostic vocabulary, not user access control. No live server logs or data are imported. |
| Private sandbox mount aliases in native runtime profiles | Paths inside isolated runtime roots, not access to the alongside live installation. Native qualification has not run here. |

**Not covered:** model-facing catalog/prompt references, social tool names in live
registrations, config defaults or user grants, server API/token inventories,
ambient cache/download fallbacks, or references used to present an unavailable
feature as implemented. Remaining operative reference findings are blockers,
not silently added to this list.
