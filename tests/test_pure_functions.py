"""Property-based and unit tests for all pure functions in ToolMux v2.0."""
import json
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from toolmux.main import (
    condense_description, condense_schema, resolve_collisions,
    enrich_result, enrich_error_result, build_gateway_description,
    build_gateway_instructions, FILLER_PHRASES,
)
from conftest import tool_dict


# ─── Strategies ───

json_types = st.sampled_from(["string", "integer", "number", "boolean", "array", "object"])

schema_property = st.fixed_dictionaries({
    "type": json_types, "description": st.text(min_size=0, max_size=50),
}).flatmap(lambda d: st.just(
    {**d, "default": "val", "enum": ["a", "b"], "examples": ["ex"]}
    if d["type"] != "array" else
    {**d, "items": {"type": "string"}, "default": [], "enum": [["a"]]}
))

json_schema_strategy = st.fixed_dictionaries({
    "type": st.just("object"),
    "properties": st.dictionaries(
        st.from_regex(r'[a-z][a-z0-9_]{0,9}', fullmatch=True),
        schema_property, min_size=1, max_size=5),
}).flatmap(lambda s: st.just({
    **s, "required": list(s["properties"].keys())[:2],
    "additionalProperties": False,
}))

tool_list_strategy = st.lists(
    st.fixed_dictionaries({
        "name": st.from_regex(r'[a-z][a-z0-9_]{2,10}', fullmatch=True),
        "_server": st.sampled_from(["server_a", "server_b", "server_c"]),
        "description": st.text(min_size=5, max_size=100),
        "inputSchema": st.just({"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}),
        "_transport": st.just("stdio"),
    }), min_size=1, max_size=10)


# ═══════════════════════════════════════════════════════════
# condense_description — Properties 1 & 2
# ═══════════════════════════════════════════════════════════

class TestCondenseDescription:
    """Property 1: respects length/word boundaries. Property 2: removes filler."""

    @given(desc=st.text(min_size=1, max_size=500),
           max_len=st.integers(min_value=10, max_value=200))
    @settings(max_examples=100)
    def test_output_never_exceeds_max_len(self, desc, max_len):
        assert len(condense_description(desc, max_len)) <= max_len

    @given(desc=st.text(min_size=1, max_size=500))
    @settings(max_examples=100)
    def test_output_never_ends_with_space(self, desc):
        result = condense_description(desc)
        if result:
            assert not result.endswith(" ")

    @given(desc=st.from_regex(r'[A-Za-z]{3,30}( [A-Za-z]{3,15}){0,3}', fullmatch=True))
    @settings(max_examples=100)
    def test_first_sentence_extracted(self, desc):
        multi = f"{desc}. Second sentence here."
        assert "Second sentence" not in condense_description(multi, max_len=200)

    @given(filler=st.sampled_from(FILLER_PHRASES))
    @settings(max_examples=100)
    def test_filler_phrases_removed(self, filler):
        result = condense_description(f"{filler} do something useful", max_len=200)
        assert filler.lower() not in result.lower()

    def test_empty_returns_empty(self):
        assert condense_description("") == ""

    def test_short_passthrough(self):
        assert condense_description("Read file contents") == "Read file contents"

    def test_trailing_period_removed(self):
        assert condense_description("Read file contents.") == "Read file contents"

    def test_no_mid_word_cut(self):
        result = condense_description("A" * 50 + " longword", max_len=55)
        assert not result.endswith("longw")


# ═══════════════════════════════════════════════════════════
# condense_schema — Property 3
# ═══════════════════════════════════════════════════════════

class TestCondenseSchema:
    """Property 3: retains structure, removes verbose fields."""

    @given(schema=json_schema_strategy)
    @settings(max_examples=100)
    def test_retains_names_types_required_removes_verbose(self, schema):
        result = condense_schema(schema)
        assert set(result["properties"].keys()) == set(schema["properties"].keys())
        assert result.get("required", []) == schema.get("required", [])
        s = json.dumps(result)
        for field in ["description", "default", "enum", "examples",
                      "additionalProperties", "minimum", "maximum"]:
            assert f'"{field}"' not in s
        for prop in result["properties"].values():
            assert "type" in prop
            if prop["type"] == "array":
                assert "items" in prop

    def test_empty_schema(self):
        assert condense_schema({}) == {"type": "object"}

    def test_no_properties(self):
        assert condense_schema({"type": "object"}) == {"type": "object"}

    def test_basic(self):
        schema = {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path"}}, "required": ["path"]}
        assert condense_schema(schema) == {
            "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

    def test_array_retains_items(self):
        schema = {"type": "object", "properties": {
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"}}}
        assert condense_schema(schema)["properties"]["tags"] == {
            "type": "array", "items": {"type": "string"}}


# ═══════════════════════════════════════════════════════════
# resolve_collisions — Property 4
# ═══════════════════════════════════════════════════════════

class TestResolveCollisions:
    """Property 4: unique names with correct prefixing."""

    @given(tools=tool_list_strategy)
    @settings(max_examples=100)
    def test_all_names_unique_after_resolution(self, tools):
        result = resolve_collisions(tools)
        names = [t["name"] for t in result]
        assert len(names) == len(set(names))

    @given(tools=tool_list_strategy)
    @settings(max_examples=100)
    def test_colliding_names_get_server_prefix(self, tools):
        counts = {}
        for t in tools:
            counts[t["name"]] = counts.get(t["name"], 0) + 1
        colliding = {n for n, c in counts.items() if c > 1}
        result = resolve_collisions(tools)
        for orig, res in zip(tools, result):
            if orig["name"] not in colliding:
                assert res["name"] == orig["name"]
            else:
                assert res["name"].startswith(f"{orig['_server']}_")

    def test_no_collision_unchanged(self):
        tools = [tool_dict(name="a", server="s1"), tool_dict(name="b", server="s2")]
        assert [t["name"] for t in resolve_collisions(tools)] == ["a", "b"]

    def test_collision_prefixed(self):
        tools = [tool_dict(name="read", server="fs"), tool_dict(name="read", server="git")]
        result = resolve_collisions(tools)
        assert result[0]["name"] == "fs_read"
        assert result[1]["name"] == "git_read"


# ═══════════════════════════════════════════════════════════
# enrich_result / enrich_error_result — Properties 5, 6, 7
# ═══════════════════════════════════════════════════════════

class TestEnrichment:
    """Properties 5-7: progressive disclosure enrichment."""

    @given(name=st.from_regex(r'[a-z][a-z0-9_]{2,10}', fullmatch=True))
    @settings(max_examples=100)
    def test_first_invocation_includes_enrichment(self, name):
        cache = [tool_dict(name=name)]
        described = set()
        result = {"content": [{"type": "text", "text": "ok"}]}
        text = enrich_result(name, result, described, cache)
        assert f"[Tool: {name}]" in text
        assert "[Description:" in text
        assert "[Parameters:" in text
        assert name in described

    @given(name=st.from_regex(r'[a-z][a-z0-9_]{2,10}', fullmatch=True))
    @settings(max_examples=100)
    def test_second_invocation_no_enrichment(self, name):
        cache = [tool_dict(name=name)]
        described = {name}
        result = {"content": [{"type": "text", "text": "ok"}]}
        text = enrich_result(name, result, described, cache)
        assert "[Tool:" not in text
        assert text == "ok"

    @given(name=st.from_regex(r'[a-z][a-z0-9_]{2,10}', fullmatch=True))
    @settings(max_examples=100)
    def test_error_always_includes_schema(self, name):
        cache = [tool_dict(name=name)]
        error = {"content": [{"type": "text", "text": "error"}], "isError": True}
        text = enrich_error_result(name, error, cache)
        assert f"[Schema for {name}:" in text


# ═══════════════════════════════════════════════════════════
# build_gateway_description — Property 12
# ═══════════════════════════════════════════════════════════

class TestBuildGatewayDescription:
    """Property 12: contains all sub-tools with descriptions and required params."""

    @given(tools=st.lists(
        st.fixed_dictionaries({
            "name": st.from_regex(r'[a-z][a-z0-9_]{2,10}', fullmatch=True),
            "description": st.text(min_size=5, max_size=100),
            "inputSchema": st.just({"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}),
        }), min_size=1, max_size=5, unique_by=lambda t: t["name"]))
    @settings(max_examples=100)
    def test_contains_all_subtool_names(self, tools):
        result = build_gateway_description(tools)
        for t in tools:
            assert t["name"] in result

    def test_includes_required_params(self):
        tools = [tool_dict(name="read_file", desc="Read file contents")]
        assert "required: x" in build_gateway_description(tools)

    def test_cached_descriptions_used(self):
        tools = [tool_dict(name="read_file")]
        assert "Custom desc" in build_gateway_description(tools, {"read_file": "Custom desc"})


# ═══════════════════════════════════════════════════════════
# build_gateway_instructions — Property 14
# ═══════════════════════════════════════════════════════════

class TestBuildGatewayInstructions:
    """Property 14: contains server summary, workflow, examples, native tool docs."""

    @given(servers=st.dictionaries(
        st.from_regex(r'[a-z][a-z_]{2,10}', fullmatch=True),
        st.integers(min_value=1, max_value=50),
        min_size=1, max_size=5))
    @settings(max_examples=100)
    def test_contains_all_required_content(self, servers):
        result = build_gateway_instructions(servers)
        for name, count in servers.items():
            assert name in result
            assert str(count) in result
        assert "get_tool_schema" in result
        assert "get_tool_count" in result
        assert "tool=" in result
        assert "arguments=" in result
