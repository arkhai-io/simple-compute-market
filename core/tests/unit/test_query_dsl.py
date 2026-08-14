from __future__ import annotations

from decimal import Decimal

import pytest

from market_core.query_dsl import (
    ComparisonOperator,
    FieldDescriptor,
    MissingValueRule,
    QuerySyntaxError,
    QueryValidationError,
    QueryValueType,
    compile_query,
    field_reference_json,
    lex_query,
    parse_query,
    render_field_reference,
)


def _descriptors() -> tuple[FieldDescriptor, ...]:
    return (
        FieldDescriptor(
            name="gpu_model",
            value_type=QueryValueType.STRING,
            operators=frozenset(
                {
                    ComparisonOperator.EQUAL,
                    ComparisonOperator.NOT_EQUAL,
                    ComparisonOperator.IN,
                    ComparisonOperator.NOT_IN,
                }
            ),
            description="GPU model",
        ),
        FieldDescriptor(
            name="gpu_count_min",
            aliases=("gpu_count",),
            value_type=QueryValueType.INTEGER,
            operators=frozenset(
                {
                    ComparisonOperator.GREATER_THAN,
                    ComparisonOperator.GREATER_THAN_OR_EQUAL,
                }
            ),
        ),
        FieldDescriptor(
            name="price",
            value_type=QueryValueType.DECIMAL,
            operators=frozenset(
                {
                    ComparisonOperator.LESS_THAN,
                    ComparisonOperator.LESS_THAN_OR_EQUAL,
                    ComparisonOperator.EQUAL,
                }
            ),
        ),
        FieldDescriptor(
            name="static_ip",
            value_type=QueryValueType.BOOLEAN,
            operators=frozenset({ComparisonOperator.EQUAL}),
            on_missing=MissingValueRule.PASS,
        ),
        FieldDescriptor(
            name="tag",
            value_type=QueryValueType.STRING,
            operators=frozenset({ComparisonOperator.EQUAL}),
            repeated=True,
        ),
    )


def test_parser_preserves_comparison_order_and_source_spans() -> None:
    source = 'gpu_model=H200 gpu_count >= 4 price<2.50 static_ip=true'
    expression = parse_query(source)

    assert [item.field for item in expression.comparisons] == [
        "gpu_model",
        "gpu_count",
        "price",
        "static_ip",
    ]
    assert expression.comparisons[0].span.start == 0
    assert expression.comparisons[1].literal.value == 4
    assert expression.comparisons[2].literal.value == Decimal("2.50")
    assert expression.comparisons[3].literal.value is True
    assert source[expression.comparisons[1].span.start : expression.comparisons[1].span.end] == "gpu_count >= 4"


def test_lexer_decodes_json_strings_without_shell_interpretation() -> None:
    tokens = lex_query(r'gpu_model="RTX 6000 Ada"')
    assert tokens[-1].value == "RTX 6000 Ada"
    assert tokens[-1].text == '"RTX 6000 Ada"'


def test_compile_normalizes_aliases_types_and_canonical_rendering() -> None:
    query = compile_query(
        'gpu_count>=04 gpu_model in [H200,"RTX 6000 Ada"] price=2.00 static_ip=false',
        _descriptors(),
    )

    assert query.comparisons[0].field == "gpu_count_min"
    assert query.comparisons[2].value == Decimal("2.00")
    assert query.render() == (
        'gpu_count_min>=4 gpu_modelin[H200,"RTX 6000 Ada"] '
        "price=2 static_ip=false"
    )


def test_repeatable_field_is_preserved_in_source_order() -> None:
    query = compile_query("tag=fast tag=local", _descriptors())
    assert [comparison.value for comparison in query.comparisons] == ["fast", "local"]


@pytest.mark.parametrize(
    ("source", "code", "position"),
    [
        ("gpu_model=(H200)", "unsupported_syntax", 10),
        ('gpu_model="unterminated', "unterminated_string", 10),
        ("gpu_model in [H200 A100]", "expected_comma", 19),
        ("gpu_model in [H200,]", "expected_list_value", 19),
        ("gpu_model=H200 or gpu_model=A100", "expected_operator", 18),
        ("gpu_model", "expected_operator", 9),
        ("gpu_model=", "expected_value", 10),
    ],
)
def test_malformed_input_has_stable_source_position(
    source: str, code: str, position: int
) -> None:
    with pytest.raises(QuerySyntaxError) as caught:
        parse_query(source)
    assert caught.value.code == code
    assert caught.value.position == position


def test_unknown_field_reports_sorted_public_vocabulary_without_value() -> None:
    secret = "sk_test_do_not_render"
    with pytest.raises(QueryValidationError) as caught:
        compile_query(f"provider_secret={secret}", _descriptors())

    payload = caught.value.to_dict()
    assert payload["code"] == "unknown_field"
    assert payload["accepted_fields"] == sorted(
        [
            "gpu_count",
            "gpu_count_min",
            "gpu_model",
            "price",
            "static_ip",
            "tag",
        ]
    )
    assert secret not in str(caught.value)
    assert secret not in str(payload)


def test_unsupported_operator_and_types_fail_closed() -> None:
    with pytest.raises(QueryValidationError, match="does not support") as operator:
        compile_query("gpu_count=4", _descriptors())
    assert operator.value.code == "unsupported_operator"

    with pytest.raises(QueryValidationError, match="requires integer") as value_type:
        compile_query("gpu_count>=four", _descriptors())
    assert value_type.value.code == "invalid_value_type"

    with pytest.raises(QueryValidationError, match="requires a list") as shape:
        compile_query("gpu_model in H200", _descriptors())
    assert shape.value.code == "invalid_value_shape"

    with pytest.raises(QueryValidationError, match="non-empty list") as empty:
        compile_query("gpu_model in []", _descriptors())
    assert empty.value.code == "empty_list"


def test_conflicting_singleton_aliases_are_rejected() -> None:
    with pytest.raises(QueryValidationError, match="may appear only once") as caught:
        compile_query("gpu_count>=2 gpu_count_min>=4", _descriptors())
    assert caught.value.code == "duplicate_field"
    assert caught.value.field == "gpu_count_min"


def test_descriptor_collisions_are_rejected() -> None:
    duplicate = FieldDescriptor(
        name="other",
        aliases=("gpu_model",),
        value_type=QueryValueType.STRING,
        operators=frozenset({ComparisonOperator.EQUAL}),
    )
    with pytest.raises(ValueError, match="duplicate query field or alias"):
        compile_query("", (*_descriptors(), duplicate))


def test_field_reference_human_and_json_are_stable_and_equivalent() -> None:
    descriptors = tuple(reversed(_descriptors()))
    payload = field_reference_json(descriptors)
    assert [item["name"] for item in payload] == [
        "gpu_count_min",
        "gpu_model",
        "price",
        "static_ip",
        "tag",
    ]
    assert payload[0] == {
        "name": "gpu_count_min",
        "aliases": ["gpu_count"],
        "value_type": "integer",
        "operators": [">", ">="],
        "on_missing": "fail",
        "repeated": False,
    }
    assert payload[1]["description"] == "GPU model"

    human = render_field_reference(descriptors)
    assert human.splitlines()[0] == (
        "gpu_count_min: integer operators=>,>= missing=fail aliases=gpu_count"
    )
    assert "gpu_model: string" in human
    assert "— GPU model" in human
    assert human.splitlines()[-1].endswith("repeated")


def test_descriptor_rejects_invalid_names_empty_operators_and_alias_duplicates() -> None:
    with pytest.raises(ValueError, match="invalid query field name"):
        FieldDescriptor(
            name="provider secret",
            value_type=QueryValueType.STRING,
            operators=frozenset({ComparisonOperator.EQUAL}),
        )
    with pytest.raises(ValueError, match="must allow an operator"):
        FieldDescriptor(
            name="field",
            value_type=QueryValueType.STRING,
            operators=frozenset(),
        )
    with pytest.raises(ValueError, match="duplicate query field alias"):
        FieldDescriptor(
            name="field",
            aliases=("field",),
            value_type=QueryValueType.STRING,
            operators=frozenset({ComparisonOperator.EQUAL}),
        )
