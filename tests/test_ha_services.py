"""The Home Assistant service model reader, and the whole statement of its behaviour.

``src/axi_toolkit/ha/services.py`` arrived as the tool's ``servicemodel.py`` with one
edit -- the module docstring pointed at a file in that repository, which would dangle
here -- and nothing below it changed. While both copies existed that last claim did not
have to be trusted: a conformance gate hashed the two files against each other with the
docstring elided and failed on any other difference. ``ha-axi`` has since deleted its
copy and imports this module, so there is one copy, the gate has been retired, and
**this file is what states the module's behaviour now** -- which is the right instrument
once the duplication is gone. AGENTS.md, "Retired gates", carries the reasoning.

**What came across, and what could not.** The tool's ``tests/test_service_model.py`` is
648 lines, and forty-five of them address this module. The rest drive ``service call``
and ``service get`` end to end against a REST double: they are tests of the command
path, they need a CLI, a fixture installation and a transport, and none of the three is
here or should be. The four cases that do address the module are below unchanged apart
from the module's new name, under "ported unchanged" -- they are the ones that encode
Home Assistant's own rules about capability masks, and rewriting them would throw away
the reason they are worded as they are.

The rest of this file is new, and it exists because of what the split above leaves
behind: eleven of the module's functions were covered only through the command path, so
after the move they would arrive here with no coverage at all. Each one is stated
directly, against a model in the shape ``GET /api/services`` returns.
"""

from __future__ import annotations

from axi_toolkit.ha import services

#: The published model, in the shape ``GET /api/services`` returns it: a list of
#: ``{"domain": ..., "services": {...}}`` entries. Deliberately uneven, because a real
#: installation is: `switch` publishes no `name` and no `description` for anything,
#: which is the ordinary case once those strings moved to the translation files that
#: `/api/services` does not serve.
MODEL = [
    {
        "domain": "light",
        "services": {
            "turn_on": {
                "name": "Turn on",
                "fields": {
                    "brightness": {"selector": {"number": {"min": 0, "max": 255}}},
                    "advanced_fields": {
                        "collapsed": True,
                        "fields": {"profile": {"selector": {"text": None}}},
                    },
                },
                "target": {"entity": [{"domain": ["light"]}]},
            },
            "turn_off": {"fields": {}, "target": {"entity": [{"domain": ["light"]}]}},
        },
    },
    {
        "domain": "switch",
        "services": {"toggle": {"fields": {"delay": {"selector": {"number": {"min": 0}}}}}},
    },
    {
        "domain": "climate",
        "services": {
            "set_temperature": {
                "fields": {
                    "temperature": {"required": True, "selector": {"number": {"min": 0}}},
                    "hvac_mode": {"selector": {"select": {"options": ["off", "heat", "cool"]}}},
                },
                "target": {"entity": [{"domain": ["climate"], "supported_features": [16]}]},
            }
        },
    },
    {
        "domain": "calendar",
        "services": {
            "get_events": {"fields": {}, "response": {"optional": True}},
            "list_events": {"fields": {}, "response": {"optional": False}},
        },
    },
]


# ------------------------------------------------------ ported unchanged
#
# The four cases from the tool's own suite that address this module rather than
# the command path. Only the module's name differs.


def test_feature_masks_are_read_only_for_the_service_own_domain():
    """An integration acting on another domain's entities publishes that domain's names.

    `reolink.ptz_move` targets `button` entities and names a `camera` feature.
    Checking a button against a camera's bits would refuse every call.
    """
    same = {"target": {"entity": [{"domain": ["media_player"], "supported_features": [8]}]}}
    assert services.feature_masks(same, "media_player") == [8]
    assert services.feature_masks(same, "reolink") == []

    cross = {"target": {"entity": [{"domain": ["button"], "supported_features": [512]}]}}
    assert services.feature_masks(cross, "reolink") == []


def test_a_capability_that_did_not_resolve_to_a_number_disables_the_gate():
    """Home Assistant resolves the enum names before publishing; anything else is unknown."""
    spec = {"target": {"entity": [{"domain": ["fan"], "supported_features": ["fan.SET_SPEED"]}]}}
    assert services.feature_masks(spec, "fan") == []


def test_satisfies_treats_the_mask_list_as_alternatives_and_each_mask_as_a_whole():
    """Home Assistant's own rule: any one mask, but every bit of that one."""
    assert services.satisfies(0b0010, [0b0010, 0b0100]) is True
    assert services.satisfies(0b0001, [0b0010, 0b0100]) is False
    # A mask of two bits is a conjunction: half of it is not enough.
    assert services.satisfies(0b0010, [0b0110]) is False
    assert services.satisfies(0b0110, [0b0110]) is True
    assert services.satisfies(0, []) is True


def test_target_domains_is_empty_when_the_service_publishes_no_restriction():
    assert services.target_domains({}) == []
    assert services.target_domains({"target": {"entity": [{}]}}) == []
    assert services.target_domains({"target": {"entity": [{"domain": "light"}]}}) == ["light"]


# ------------------------------------------------------------ reading the model


def test_the_domains_are_every_registered_one_sorted():
    assert services.domains(MODEL) == ["calendar", "climate", "light", "switch"]


def test_a_model_that_is_not_the_published_shape_reads_as_empty_rather_than_raising():
    """The model is fetched, so it is whatever came back -- including nothing.

    A caller reaches for this on the failure path, to explain a refusal. Raising
    there would replace the error the agent needs with one about the explanation.
    """
    assert services.domains(None) == []
    assert services.domains({"domain": "light"}) == []
    assert services.domains(["light", None, {"domain": "light"}]) == ["light"]
    assert services.domains([{"services": {}}]) == []
    assert services.find_domain(None, "light") is None
    assert services.service_names(None, "light") == []
    assert services.find_service(None, "light", "turn_on") is None


def test_one_domains_entry_is_returned_whole_and_a_missing_one_is_none():
    entry = services.find_domain(MODEL, "switch")
    assert entry is not None
    assert sorted(entry["services"]) == ["toggle"]
    assert services.find_domain(MODEL, "lightt") is None


def test_the_service_names_of_a_domain_are_sorted_and_a_missing_domain_has_none():
    assert services.service_names(MODEL, "light") == ["turn_off", "turn_on"]
    assert services.service_names(MODEL, "lightt") == []


def test_a_domain_whose_services_key_is_not_a_mapping_has_no_services():
    """Defensive on purpose: this reads a payload, not a value this package built."""
    broken = [{"domain": "light", "services": None}]
    assert services.service_names(broken, "light") == []
    assert services.find_service(broken, "light", "turn_on") is None


def test_one_service_description_is_returned_and_an_unregistered_one_is_none():
    spec = services.find_service(MODEL, "light", "turn_on")
    assert spec is not None
    assert spec["name"] == "Turn on"
    assert services.find_service(MODEL, "light", "turn_onn") is None
    assert services.find_service(MODEL, "lightt", "turn_on") is None


def test_a_service_description_that_is_not_a_mapping_reads_as_unregistered():
    broken = [{"domain": "light", "services": {"turn_on": "not a description"}}]
    assert services.find_service(broken, "light", "turn_on") is None


# ------------------------------------------------------------- the near misses


def test_a_wrong_name_gets_the_names_it_plausibly_meant():
    assert services.near("turn_onn", ["turn_on", "turn_off", "toggle"]) == ["turn_on", "turn_off"]


def test_a_name_too_far_off_gets_nothing_rather_than_a_wrong_guess():
    """Padding this out with whatever else exists turns "did you mean" into a claim.

    The caller lists the rest in a separate sentence, which reads as one.
    """
    assert services.near("zzzzzzzz", ["turn_on", "turn_off", "toggle"]) == []


def test_a_shared_prefix_counts_even_when_the_edit_distance_does_not():
    """`media_next_track` is nothing like `med` by ratio, and is obviously what was meant."""
    assert services.near("med", ["media_next_track", "media_play"]) == [
        "media_next_track",
        "media_play",
    ]


def test_a_prefix_shorter_than_three_characters_is_not_treated_as_one():
    """Two characters match too much to be a suggestion."""
    assert services.near("me", ["media_next_track", "media_play"]) == []


def test_the_suggestion_list_is_capped_and_empty_candidates_are_dropped():
    assert len(services.near("turn", ["turn_a", "turn_b", "turn_c", "turn_d"], limit=2)) == 2
    assert services.near("turn_on", ["", None, "turn_on"]) == ["turn_on"]


# ------------------------------------------------------------------- the fields


def test_a_section_is_flattened_and_named_as_the_section_it_came_from():
    """Home Assistant validates the service data flat; a section is a display grouping.

    Reporting the section as though it were itself a field would invite an agent to
    send it.
    """
    spec = services.find_service(MODEL, "light", "turn_on")
    assert services.fields(spec) == [
        ("brightness", {"selector": {"number": {"min": 0, "max": 255}}}, ""),
        ("profile", {"selector": {"text": None}}, "advanced_fields"),
    ]
    assert services.field_names(spec) == ["brightness", "profile"]


def test_a_service_that_declares_no_fields_declares_none():
    assert services.fields({}) == []
    assert services.fields({"fields": None}) == []
    assert services.fields({"fields": {}}) == []
    assert services.field_names({"fields": {}}) == []


def test_a_field_that_is_not_a_mapping_is_kept_as_a_field_with_nothing_declared():
    """Dropping it would hide a name the service does accept."""
    assert services.fields({"fields": {"delay": None}}) == [("delay", {}, "")]
    assert services.fields({"fields": {"g": {"fields": {"inner": None}}}}) == [("inner", {}, "g")]


def test_only_the_fields_marked_required_are_required():
    spec = services.find_service(MODEL, "climate", "set_temperature")
    assert services.required_field_names(spec) == ["temperature"]
    assert services.required_field_names({"fields": {}}) == []


def test_the_targeting_keys_are_not_declared_fields_anywhere_in_the_model():
    """Which is why an unknown-field check has to allow them explicitly."""
    assert services.TARGET_KEYS == ("entity_id", "device_id", "area_id", "floor_id", "label_id")
    for domain in services.domains(MODEL):
        for name in services.service_names(MODEL, domain):
            declared = services.field_names(services.find_service(MODEL, domain, name))
            assert not set(declared) & set(services.TARGET_KEYS)


# ---------------------------------------------------------------- the selectors


def test_a_selector_reports_the_one_word_type_it_declares():
    spec = services.find_service(MODEL, "climate", "set_temperature")
    by_name = {name: field for name, field, _ in services.fields(spec)}
    assert services.selector_kind(by_name["temperature"]) == "number"
    assert services.selector_kind(by_name["hvac_mode"]) == "select"


def test_a_field_with_no_usable_selector_declares_no_type():
    assert services.selector_kind({}) == ""
    assert services.selector_kind({"selector": {}}) == ""
    assert services.selector_kind({"selector": None}) == ""


def test_a_select_selector_lists_the_values_it_accepts_so_a_miss_can_name_them():
    spec = services.find_service(MODEL, "climate", "set_temperature")
    by_name = {name: field for name, field, _ in services.fields(spec)}
    assert services.selector_options(by_name["hvac_mode"]) == ["off", "heat", "cool"]


def test_select_options_published_as_objects_are_reduced_to_their_values():
    field = {"selector": {"select": {"options": [{"value": "off", "label": "Off"}, "heat"]}}}
    assert services.selector_options(field) == ["off", "heat"]


def test_anything_that_is_not_a_select_selector_has_no_options():
    assert services.selector_options({}) == []
    assert services.selector_options({"selector": None}) == []
    assert services.selector_options({"selector": {"number": {"min": 0}}}) == []
    assert services.selector_options({"selector": {"select": None}}) == []
    assert services.selector_options({"selector": {"select": {"options": None}}}) == []


# ------------------------------------------------------------ the response mode


def test_a_service_that_cannot_answer_publishes_no_response_key_at_all():
    assert services.response_mode(services.find_service(MODEL, "light", "turn_on")) == "none"
    assert services.response_mode({}) == services.RESPONSE_NONE
    assert services.response_mode({"response": None}) == services.RESPONSE_NONE


def test_optional_false_means_the_service_answers_or_does_nothing():
    """So the two published spellings are not "may answer" and "must not"."""
    assert services.response_mode(services.find_service(MODEL, "calendar", "get_events")) == (
        services.RESPONSE_OPTIONAL
    )
    assert services.response_mode(services.find_service(MODEL, "calendar", "list_events")) == (
        services.RESPONSE_REQUIRED
    )


def test_the_three_response_modes_are_the_words_a_caller_prints():
    assert (services.RESPONSE_NONE, services.RESPONSE_OPTIONAL, services.RESPONSE_REQUIRED) == (
        "none",
        "optional",
        "required",
    )


# ---------------------------------------------------------------- the target


def test_the_target_domains_are_the_union_of_every_entity_entry_sorted():
    spec = {
        "target": {
            "entity": [
                {"domain": ["switch", "light"]},
                {"domain": "light"},
                "not an entry",
            ]
        }
    }
    assert services.target_domains(spec) == ["light", "switch"]


def test_one_entry_with_no_domain_drops_the_restriction_for_the_whole_service():
    """`homeassistant.turn_on` reaches every domain by design; a partial list would lie."""
    spec = {"target": {"entity": [{"domain": ["light"]}, {"supported_features": [1]}]}}
    assert services.target_domains(spec) == []


def test_a_target_that_is_not_the_published_shape_publishes_no_restriction():
    assert services.target_domains({"target": None}) == []
    assert services.target_domains({"target": {}}) == []
    assert services.target_domains({"target": {"entity": None}}) == []


# ------------------------------------------------------------ the capability gate


def test_a_service_with_no_published_capability_gates_nothing():
    assert services.feature_masks({}, "light") == []
    assert services.feature_masks({"target": None}, "light") == []
    assert services.feature_masks({"target": {"entity": None}}, "light") == []
    assert services.feature_masks({"target": {"entity": [{"domain": ["light"]}]}}, "light") == []


def test_more_than_one_entity_entry_disables_the_gate():
    """Which entry the resolved target would fall under is not knowable from here."""
    spec = {
        "target": {
            "entity": [
                {"domain": ["light"], "supported_features": [1]},
                {"domain": ["switch"], "supported_features": [2]},
            ]
        }
    }
    assert services.feature_masks(spec, "light") == []


def test_a_domain_published_as_a_bare_string_is_read_the_same_as_a_list_of_one():
    spec = {"target": {"entity": [{"domain": "light", "supported_features": [1]}]}}
    assert services.feature_masks(spec, "light") == [1]


def test_one_unresolved_mask_disables_the_gate_rather_than_narrowing_it():
    """Keeping the half that parsed would gate on a capability nobody published."""
    spec = {"target": {"entity": [{"domain": ["light"], "supported_features": [1, "TRANSITION"]}]}}
    assert services.feature_masks(spec, "light") == []


def test_a_mask_that_is_a_boolean_or_zero_is_not_a_capability():
    """`True` is an `int` in Python and would gate on bit 0, which is a real feature."""
    for mask in (True, False, 0, -1):
        spec = {"target": {"entity": [{"domain": ["light"], "supported_features": [mask]}]}}
        assert services.feature_masks(spec, "light") == [], mask


def test_an_entity_entry_that_is_not_a_mapping_publishes_no_masks():
    assert services.feature_masks({"target": {"entity": ["light"]}}, "light") == []


def test_a_state_that_reports_no_capability_bits_reports_none_rather_than_failing():
    """Absent, `null` and `true` all mean "this state does not say", which is zero."""
    assert services.entity_features({"attributes": {"supported_features": 44}}) == 44
    assert services.entity_features({"attributes": {}}) == 0
    assert services.entity_features({"attributes": None}) == 0
    assert services.entity_features({}) == 0
    assert services.entity_features({"attributes": {"supported_features": None}}) == 0
    assert services.entity_features({"attributes": {"supported_features": True}}) == 0
    assert services.entity_features({"attributes": {"supported_features": "44"}}) == 0
