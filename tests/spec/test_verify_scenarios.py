"""Standalone mathematical and structural verifier for MiniScenarioVector in SpecRule JSON files.

Uses ONLY the Python standard library and `dateutil.rrule` via `oracle_temporal`
(zero imports from `ical`).
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest

from .oracle_temporal import (
    ParsedTemporal,
    StoreError,
    expand_component_candidates,
    format_canonical_rid,
    parse_temporal as _raw_parse_temporal,
)
from .schema import (
    RULES_DIR,
    SpecRule,
    load_all_scenarios,
    load_rules_from_path,
    verify_path,
    verify_rule,
)


def parse_temporal(
    raw: str, field_name: str = ""
) -> tuple[ParsedTemporal | None, list[str]]:
    """Parse a temporal string and return (ParsedTemporal | None, error_messages)."""
    try:
        return _raw_parse_temporal(raw, field_name), []
    except (StoreError, ValueError) as exc:
        return None, [f"{field_name}: {exc}"]


def expand_master_occurrences(
    comp: dict[str, Any],
) -> tuple[list[tuple[str, ParsedTemporal, datetime.timedelta | None]], list[str]]:
    """Expand a recurring component's candidate set (RRULE + RDATE - EXDATE) and collect errors."""
    try:
        for ex_raw in comp.get("exdate") or ():
            pt_start = _raw_parse_temporal(comp["dtstart"], "dtstart")
            pt_ex = _raw_parse_temporal(ex_raw, "exdate")
            if pt_start.kind != pt_ex.kind:
                return [], [
                    f"EXDATE timezone/type mismatch in {comp.get('uid')}: DTSTART is {pt_start.kind} "
                    f"but EXDATE is {pt_ex.kind} ({ex_raw})"
                ]
        return expand_component_candidates(comp, include_exdates=False), []
    except (StoreError, ValueError) as exc:
        return [], [f"Failed to expand component {comp.get('uid')}: {exc}"]


def _verify_single_component(
    comp: dict[str, Any],
    idx: int,
    prefix: str,
    seen_keys: set[tuple[str, str | None]],
) -> list[str]:
    """Verify structural and temporal invariants on a single component dictionary."""
    errors: list[str] = []
    ctype = comp.get("type", "VEVENT")
    if ctype == "VTIMEZONE":
        if not comp.get("tz_id"):
            errors.append(f"{prefix} VTIMEZONE component missing tz_id")
        return errors

    uid = comp.get("uid")
    if not uid:
        return [f"{prefix} Component #{idx} missing uid"]

    raw_rid = comp.get("recurrence_id")
    norm_rid: str | None = None
    if raw_rid is not None:
        pt_rid, r_errs = parse_temporal(raw_rid, "recurrence_id")
        errors.extend(f"{prefix} {e}" for e in r_errs)
        norm_rid = format_canonical_rid(pt_rid) if pt_rid else raw_rid

    key = (uid, norm_rid)
    if key in seen_keys:
        errors.append(
            f"{prefix} Duplicate component (uid={uid!r}, recurrence_id={raw_rid!r})"
        )
    seen_keys.add(key)

    pt_start: ParsedTemporal | None = None
    if (dtstart_raw := comp.get("dtstart")) is not None:
        pt_start, s_errs = parse_temporal(dtstart_raw, "dtstart")
        errors.extend(f"{prefix} {e}" for e in s_errs)

    if (dtend_raw := comp.get("dtend")) is not None:
        pt_end, e_errs = parse_temporal(dtend_raw, "dtend")
        errors.extend(f"{prefix} {e}" for e in e_errs)
        if pt_start and pt_end and pt_end.dt_utc_or_naive <= pt_start.dt_utc_or_naive:
            errors.append(
                f"{prefix} DTEND ({dtend_raw}) must be > DTSTART ({dtstart_raw}) on {uid}"
            )

    if (due_raw := comp.get("due")) is not None:
        pt_due, d_errs = parse_temporal(due_raw, "due")
        errors.extend(f"{prefix} {e}" for e in d_errs)
        if pt_start and pt_due and pt_due.dt_utc_or_naive < pt_start.dt_utc_or_naive:
            errors.append(
                f"{prefix} DUE ({due_raw}) must be >= DTSTART ({dtstart_raw}) on {uid}"
            )

    for meta_field in ("dtstamp", "created", "last_modified", "completed"):
        if (val := comp.get(meta_field)) is not None:
            pt_m, m_errs = parse_temporal(val, meta_field)
            errors.extend(f"{prefix} {e}" for e in m_errs)
            if pt_m and pt_m.kind != "UTC":
                errors.append(f"{prefix} {meta_field} ({val}) must be UTC (Z)")

    if raw_rid is not None and not comp.get("rrule"):
        if comp.get("rdate"):
            errors.append(
                f"{prefix} Standalone override (uid={uid}, rid={raw_rid}) has non-empty rdate"
            )
        if comp.get("exdate"):
            errors.append(
                f"{prefix} Standalone override (uid={uid}, rid={raw_rid}) has non-empty exdate"
            )
    return errors


def verify_component_list(
    components: list[dict[str, Any]], label: str, rule_id: str, scenario_name: str
) -> list[str]:
    """Check invariants on a list of component dicts."""
    errors: list[str] = []
    prefix = f"[{rule_id} :: {scenario_name} :: {label}]"
    seen_keys: set[tuple[str, str | None]] = set()
    for idx, comp in enumerate(components):
        errors.extend(_verify_single_component(comp, idx, prefix, seen_keys))
    return errors


def _verify_timeline_chronology(exp_tl: list[dict[str, Any]], prefix: str) -> list[str]:
    """Verify chronological sorting and start/end ordering of expected_timeline."""
    errors: list[str] = []
    tl_sort_keys: list[tuple[datetime.datetime, str, str]] = []
    for idx, item in enumerate(exp_tl):
        uid = item.get("uid", "")
        dtstart_raw = item.get("dtstart")
        rid_raw = item.get("recurrence_id") or ""
        if dtstart_raw:
            pt_s, s_errs = parse_temporal(dtstart_raw, "timeline.dtstart")
            errors.extend(f"{prefix} timeline[{idx}]: {e}" for e in s_errs)
            if pt_s:
                tl_sort_keys.append((pt_s.dt_utc_or_naive, uid, rid_raw))
        if item.get("dtend") and dtstart_raw:
            pt_s, _ = parse_temporal(dtstart_raw, "timeline.dtstart")
            pt_e, e_errs = parse_temporal(item["dtend"], "timeline.dtend")
            errors.extend(f"{prefix} timeline[{idx}]: {e}" for e in e_errs)
            if pt_s and pt_e and pt_e.dt_utc_or_naive <= pt_s.dt_utc_or_naive:
                errors.append(
                    f"{prefix} timeline[{idx}]: DTEND ({item['dtend']}) <= DTSTART ({dtstart_raw})"
                )
    if tl_sort_keys and tl_sort_keys != sorted(tl_sort_keys):
        errors.append(
            f"{prefix} expected_timeline is not sorted chronologically: {[k[0].isoformat() for k in tl_sort_keys]}"
        )
    return errors


def _verify_single_occurrence_match(
    uid: str,
    idx: int,
    rid_key: str,
    pt_occ: ParsedTemporal,
    dur: datetime.timedelta | None,
    src_comp: dict[str, Any],
    tl_item: dict[str, Any],
    prefix: str,
) -> list[str]:
    """Compare one reconstructed occurrence against one expected_timeline item."""
    errors: list[str] = []
    for prop in ("summary", "sequence"):
        if prop in tl_item and prop in src_comp and tl_item[prop] != src_comp[prop]:
            errors.append(
                f"{prefix} UID {uid!r} occ #{idx}: timeline {prop} {tl_item[prop]!r} != component {src_comp[prop]!r}"
            )
    if "dtstart" in tl_item:
        pt_tl_s, _ = parse_temporal(tl_item["dtstart"], "tl.dtstart")
        if pt_tl_s and pt_tl_s.dt_utc_or_naive != pt_occ.dt_utc_or_naive:
            errors.append(
                f"{prefix} UID {uid!r} occ #{idx}: timeline dtstart {tl_item['dtstart']!r} != expanded {pt_occ.raw!r}"
            )
    for end_key in ("dtend", "due"):
        if end_key in tl_item and tl_item[end_key] is not None:
            pt_tl_e, _ = parse_temporal(tl_item[end_key], f"tl.{end_key}")
            if dur is not None and pt_tl_e is not None:
                expected_end = pt_occ.value + dur
                exp_cmp = (
                    (
                        expected_end.astimezone(datetime.timezone.utc).replace(
                            tzinfo=None
                        )
                        if expected_end.tzinfo is not None
                        else expected_end
                    )
                    if isinstance(expected_end, datetime.datetime)
                    else datetime.datetime(
                        expected_end.year, expected_end.month, expected_end.day
                    )
                )
                if pt_tl_e.dt_utc_or_naive != exp_cmp:
                    errors.append(
                        f"{prefix} UID {uid!r} occ #{idx}: timeline {end_key} {tl_item[end_key]!r} != expanded {expected_end!r}"
                    )
            elif dur is None and end_key in src_comp and pt_tl_e is not None:
                pt_src_e, _ = parse_temporal(src_comp[end_key], f"src.{end_key}")
                if pt_src_e and pt_tl_e.dt_utc_or_naive != pt_src_e.dt_utc_or_naive:
                    errors.append(
                        f"{prefix} UID {uid!r} occ #{idx}: timeline {end_key} {tl_item[end_key]!r} != override {src_comp[end_key]!r}"
                    )
    if "recurrence_id" in tl_item and tl_item["recurrence_id"] is not None:
        pt_tl_r, _ = parse_temporal(tl_item["recurrence_id"], "tl.recurrence_id")
        norm_tl_r = (
            format_canonical_rid(pt_tl_r) if pt_tl_r else tl_item["recurrence_id"]
        )
        if norm_tl_r != rid_key:
            errors.append(
                f"{prefix} UID {uid!r} occ #{idx}: timeline recurrence_id {tl_item['recurrence_id']!r} != expanded {rid_key!r}"
            )
    return errors


def _verify_uid_reconstructed_timeline(
    uid: str,
    u_comps: list[dict[str, Any]],
    u_tl: list[dict[str, Any]],
    prefix: str,
) -> list[str]:
    """Reconstruct occurrences for one UID and verify against its expected_timeline items."""
    errors: list[str] = []
    recurring_comps = [
        c
        for c in u_comps
        if c.get("rrule") or c.get("rdate") or c.get("recurrence_id") is None
    ]
    standalone_overrides = [
        c
        for c in u_comps
        if c.get("recurrence_id") is not None
        and not c.get("rrule")
        and not c.get("rdate")
    ]
    expanded_map: dict[
        str, tuple[ParsedTemporal, datetime.timedelta | None, dict[str, Any]]
    ] = {}
    for rc in recurring_comps:
        if not rc.get("dtstart"):
            continue
        occs, exp_errs = expand_master_occurrences(rc)
        errors.extend(f"{prefix} {e}" for e in exp_errs)
        for rid_str, pt_occ, dur in occs:
            expanded_map[rid_str] = (pt_occ, dur, rc)

    for ov in standalone_overrides:
        pt_rid, _ = parse_temporal(ov["recurrence_id"], "override.recurrence_id")
        norm_rid = format_canonical_rid(pt_rid) if pt_rid else ov["recurrence_id"]
        pt_ov_start, _ = parse_temporal(ov["dtstart"], "override.dtstart")
        if pt_ov_start:
            expanded_map[norm_rid] = (pt_ov_start, None, ov)

    reconstructed = sorted(
        expanded_map.items(), key=lambda kv: kv[1][0].dt_utc_or_naive
    )
    if not reconstructed and u_tl:
        return errors
    if len(reconstructed) != len(u_tl):
        return [
            f"{prefix} UID {uid!r}: expected_components expands to {len(reconstructed)} occurrences, "
            f"but expected_timeline has {len(u_tl)} items"
        ]
    for idx, ((rid_key, (pt_occ, dur, src_comp)), tl_item) in enumerate(
        zip(reconstructed, u_tl)
    ):
        errors.extend(
            _verify_single_occurrence_match(
                uid, idx, rid_key, pt_occ, dur, src_comp, tl_item, prefix
            )
        )
    return errors


def verify_scenario(rule_id: str, scenario: dict[str, Any]) -> list[str]:
    """Verify all structural and mathematical invariants on a single MiniScenarioVector."""
    sname = scenario.get("name", "<unnamed>")
    prefix = f"[{rule_id} :: {sname}]"
    init_comps = scenario.get("initial_components", [])
    exp_comps = scenario.get("expected_components", [])
    exp_tl = scenario.get("expected_timeline", [])

    errors = [
        *verify_component_list(init_comps, "initial_components", rule_id, sname),
        *verify_component_list(exp_comps, "expected_components", rule_id, sname),
        *_verify_timeline_chronology(exp_tl, prefix),
    ]

    comps_by_uid: dict[str, list[dict[str, Any]]] = {}
    for comp in exp_comps:
        if comp.get("type") != "VTIMEZONE" and (uid := comp.get("uid")):
            comps_by_uid.setdefault(uid, []).append(comp)

    tl_by_uid: dict[str, list[dict[str, Any]]] = {}
    for item in exp_tl:
        if uid := item.get("uid"):
            tl_by_uid.setdefault(uid, []).append(item)

    if set(comps_by_uid.keys()) != set(tl_by_uid.keys()):
        errors.append(
            f"{prefix} UIDs in expected_components ({set(comps_by_uid.keys())}) != "
            f"UIDs in expected_timeline ({set(tl_by_uid.keys())})"
        )
    for uid, u_comps in comps_by_uid.items():
        errors.extend(
            _verify_uid_reconstructed_timeline(
                uid, u_comps, tl_by_uid.get(uid, []), prefix
            )
        )
    return errors


ALL_RULES = load_rules_from_path(RULES_DIR)
ALL_SCENARIOS = load_all_scenarios()


def test_rule_directory_completeness() -> None:
    """Verify that all 38 rules exist with unique IDs and zero citation/clean-room errors."""
    count, errors = verify_path(RULES_DIR)
    assert count == 38
    assert not errors


@pytest.mark.parametrize("rule", ALL_RULES, ids=[r.id for r in ALL_RULES])
def test_spec_rule_citations_and_clean_room(rule: SpecRule) -> None:
    """Verify RFC citation grounding and clean-room independence for each SpecRule."""
    errors = verify_rule(rule)
    assert not errors, f"Rule {rule.id} failed verification: {errors}"


@pytest.mark.parametrize(
    ("rule_id", "scen_idx", "scen_name", "scenario"),
    ALL_SCENARIOS,
    ids=[f"{r}[{i}]-{n}" for r, i, n, _ in ALL_SCENARIOS],
)
def test_scenario_mathematical_and_structural_invariants(
    rule_id: str, scen_idx: int, scen_name: str, scenario: dict[str, Any]
) -> None:
    """Verify mathematical and structural RFC invariants on each MiniScenarioVector."""
    errors = verify_scenario(rule_id, scenario)
    assert not errors, (
        f"Scenario {rule_id}[{scen_idx}] ({scen_name}) failed invariant verification: {errors}"
    )
