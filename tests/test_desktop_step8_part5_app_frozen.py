"""Exact inherited engine assertions underlying the app-owned step-8 cases.

Only unused imports and the inert removed Discord Config constructor keyword
are projected out. No assertions, parameters, decorators or test signatures
are rewritten. ProviderOwner uses this same retained gateway and clients.
"""

from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, frozen_source

REASONING = (
    "test_all_dialect_consumers_share_preset_defaults",
    "test_deepseek_public_requests_accept_model_keyword",
    "test_one_token_probe_only_accepts_expected_output_exhaustion",
    "test_empty_output_is_not_success",
    "test_native_effort_names_do_not_crash_translation",
    "test_full_neutral_scale_maps_to_thinking_modes",
    "test_compatible_primary_identity_resolves_neutral_effort",
    "test_legacy_primary_thinking_mode_migrates_to_neutral_effort",
    "test_compatible_primary_effort_reaches_native_wire_body",
    "test_profile_uses_pins_and_independently_limiting_routes",
)


SUITES = {
    "campaign_reasoning_contracts":
        "272948b6069758a0802e296ed98c3087cfd028b8558f189b53fb65d6429fbad5",
    "schedule_report_format_parity":
        "3dc99150535cddcd53187dcebaa2af8f0859b4837a2d298f6d253e278d64ff4a",
}
CONFIG_RULES = {
    37: (
        "bcf7c50fbb000d8d96794e42fea885d3641c1dd495248ba8a4402209d4574ba4",
        "ba575016c6b259eebae1e59fad981eccdb780604b487da8043117406aab2db67",
    ),
    90: (
        "bc75bc1730ab31aa59ffb23e52d33806ad02f13f35509125545f90eaabc02d43",
        "806ee1d928ed54fe11e081ec96231eec6753b7d4c37fc703a30f81e38381712a",
    ),
    120: (
        "c2b559c2f547161ab316d0b3f0cc50d97a6d433ca0751b33634df4c39e9f93bf",
        "22afeaaf2d67ab1cee840d8523d5df6b5a02f6a70d247db8e0bbe4078b47bee2",
    ),
    146: (
        "89902a21f04c60c2ad337da3b1e8f2194efd1a9e130309373dc8dcdd6638d0ab",
        "85252f4e58e1cdc3d074d8247380de1dc640cba8ee33637ff44ee219beb9bef7",
    ),
    173: (
        "cbcf4057ec6c18dd0b338e1a94f0b10e0b44f8946b6b248edea24f99027add79",
        "63c4fa110ecb4a588dbe3fc7f339124efd87b970d1084fd7a8146f41fed0fd60",
    ),
}
IMPORT_RULES = {
    "campaign_reasoning_contracts": {
        13: "b9c10e1af46440a413eaa1f2f2bad6a26814b781d5f7ae94c5ffb72d8cf94813",
    },
    "schedule_report_format_parity": {
        7: "2d6919324ac7cf4ec37088f94992b0b93f563a86b51473d0da2ca0e058032cf1",
        10: "a0c8a3ee1fb55acca6867b117626b229375714519d5a79fddc907f96959d39cd",
    },
}


def ast_hash(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def adapted_tree(stem):
    path = f"tests/test_{stem}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[stem]:
        raise AssertionError("frozen suite bytes changed")
    original = ast.parse(source, filename=path)
    adapted = copy.deepcopy(original)
    replacements = []
    rules = CONFIG_RULES if stem == "campaign_reasoning_contracts" else {}
    for line, (before, after) in rules.items():
        matches = [node for node in ast.walk(adapted)
                   if isinstance(node, ast.Call) and node.lineno == line
                   and ast_hash(node) == before]
        if len(matches) != 1:
            raise AssertionError("sealed Config fixture not unique")
        node = matches[0]
        old = copy.deepcopy(node)
        keyword = next(k for k in node.keywords if k.arg == "discord")
        node.keywords.remove(keyword)
        if ast_hash(node) != after:
            raise AssertionError("sealed Config result changed")
        replacements.append((node, old))
    if stem == "campaign_reasoning_contracts":
        before = "7b3614f54943ff6ddee250990e5910d431c3581a5d22b4b25a1bd99c4ba3354a"
        matches = [node for node in ast.walk(adapted)
                   if isinstance(node, ast.Constant) and node.lineno == 44
                   and ast_hash(node) == before]
        if len(matches) != 1:
            raise AssertionError("sealed source-consumer fixture not unique")
        node = matches[0]
        old = copy.deepcopy(node)
        node.value = "src/desktop/providers.py"
        if ast_hash(node) != "e9be4184e3bfd806da2639d4db23113846783f3ea25ff1218c4fe4b0f911e75e":
            raise AssertionError("sealed source-consumer replacement changed")
        replacements.append((node, old))
    if corpus(original) != corpus(adapted):
        raise AssertionError("full inherited assertion/signature/parameter corpus changed")
    reverse = copy.deepcopy(adapted)
    for changed, old in replacements:
        matches = [node for node in ast.walk(reverse)
                   if type(node) is type(changed) and node.lineno == changed.lineno
                   and ast_hash(node) == ast_hash(changed)]
        if len(matches) != 1:
            raise AssertionError("reverse setup hunk not unique")
        matches[0].__dict__.clear()
        matches[0].__dict__.update(copy.deepcopy(old.__dict__))
    if ast.dump(reverse, include_attributes=True) != ast.dump(original, include_attributes=True):
        raise AssertionError("reverse setup proof failed")
    projected_imports = []
    for line, expected in IMPORT_RULES[stem].items():
        matches = [node for node in adapted.body
                   if isinstance(node, ast.ImportFrom) and node.lineno == line
                   and ast_hash(node) == expected]
        if len(matches) != 1:
            raise AssertionError("unused original import projection changed")
        projected_imports.append(copy.deepcopy(matches[0]))
        adapted.body.remove(matches[0])
    # Invert the import projection as well; no unexplained module-level edit.
    restored = copy.deepcopy(adapted)
    restored.body.extend(projected_imports)
    restored.body.sort(key=lambda node: node.lineno)
    for changed, old in replacements:
        matches = [node for node in ast.walk(restored)
                   if type(node) is type(changed) and node.lineno == changed.lineno
                   and ast_hash(node) == ast_hash(changed)]
        if len(matches) != 1:
            raise AssertionError("projected inverse hunk not unique")
        matches[0].__dict__.clear()
        matches[0].__dict__.update(copy.deepcopy(old.__dict__))
    if ast.dump(restored, include_attributes=True) != ast.dump(original, include_attributes=True):
        raise AssertionError("full module projection inverse proof failed")
    return original, adapted


def export(namespace, stem, selection):
    path = f"tests/test_{stem}.py"
    original, adapted = adapted_tree(stem)
    # Removing unused imports is setup projection, not a shadow implementation.
    adapted.body = [node for node in adapted.body if not (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_") and node.name not in selection
    )]
    present = {node.name for node in adapted.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name.startswith("test_")}
    if present != set(selection):
        raise AssertionError("unknown or extra frozen case selection")
    ast.fix_missing_locations(adapted)
    module = ModuleType(f"desktop_step8_part5_{stem}")
    module.__file__ = path
    exec(compile(adapted, path, "exec"), module.__dict__)
    for name in selection:
        namespace[f"test_{stem}_{name[5:]}"] = getattr(module, name)


export(globals(), "campaign_reasoning_contracts", REASONING)
export(globals(), "schedule_report_format_parity",
       ("test_native_tool_schemas_agree_on_report_format",))


def test_step8_part5_frozen_setup_provenance():
    for stem in SUITES:
        original, adapted = adapted_tree(stem)
        assert corpus(original) == corpus(adapted)
