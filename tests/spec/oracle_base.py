"""Clean-room Base Store Class and Segment/Override Helpers for ReferenceStore.

Implements shared metadata lifecycle (R-L5-001, R-L5-002, R-L5-003, R-L5-004),
VTIMEZONE registration (R-L5-005, R-L5-006), candidate-based series lookup (R-L3-002,
R-L3-006), the legacy shared-UID write guard (R-L3-009), and DST-safe duration/truncation/shift
delegation (R-L3-003, R-L3-007, R-L4-004, R-L4-005).
"""

from __future__ import annotations

import datetime
from typing import Any

from .oracle_canonical import (
    DEFAULT_DTSTAMP,
    canonicalize_component,
    is_parent_relation,
    max_utc_timestamp,
    normalize_range,
    validate_component_state,
    validate_related_to,
)
from .oracle_policy import (
    PolicyConfig,
    SeriesRescheduleExceptionMode,
    StoreError,
)
from .oracle_schedule import (
    align_rrule_until_on_dtstart_change,
    compute_component_duration,
    filter_valid_exdates,
    shift_comp_end_or_due,
    shift_override_in_place,
    truncate_segment_terms,
)
from .oracle_temporal import (
    ParsedTemporal,
    align_rid_to_master,
    compute_wall_clock_delta,
    expand_component_candidates,
    format_canonical_rid,
    parse_temporal,
    temporal_class,
)


def _check_override_pair(
    ov: dict[str, Any], main: dict[str, Any], *, check_candidate: bool
) -> None:
    """Validate I-K-003, I-K-004, I-K-005 (optional), and I-K-007 between ov and main."""
    if not (main.get("rrule") or main.get("rdate")):
        raise StoreError(
            f"Override on uid={ov['uid']!r} requires a recurring main (I-K-003)"
        )
    if ov.get("type") != main.get("type"):
        raise StoreError(
            f"Override type mismatches main on uid={ov['uid']!r} (I-K-003)"
        )
    pt_main = parse_temporal(main["dtstart"], "dtstart")
    pt_rid = parse_temporal(ov["recurrence_id"], "recurrence_id")
    pt_ov_s = parse_temporal(ov["dtstart"], "dtstart")
    if temporal_class(pt_rid) != temporal_class(pt_main):
        raise StoreError(
            f"Override RECURRENCE-ID {ov['recurrence_id']!r} form mismatches main DTSTART (R-L1-007)"
        )
    if temporal_class(pt_ov_s) != temporal_class(pt_main):
        raise StoreError(
            f"Override DTSTART {ov['dtstart']!r} form mismatches main DTSTART (I-K-007)"
        )
    if check_candidate:
        canon_rid = format_canonical_rid(
            align_rid_to_master(ov["recurrence_id"], pt_main)
        )
        cands = {
            rid for rid, _, _ in expand_component_candidates(main, include_exdates=True)
        }
        if canon_rid not in cands:
            raise StoreError(
                f"Override RECURRENCE-ID {ov['recurrence_id']!r} is not a candidate of main (I-K-005)"
            )


class OracleBase:
    """Base class providing canonical state, validation, and segment helpers for ReferenceStore."""

    def __init__(
        self,
        initial_components: list[dict[str, Any]] | None = None,
        policy: PolicyConfig | None = None,
    ) -> None:
        self.policy = policy or PolicyConfig()
        self.components: list[dict[str, Any]] = []
        for raw_comp in initial_components or ():
            if raw_comp.get("type") == "VTIMEZONE":
                tz_id = raw_comp.get("tz_id")
                if not isinstance(tz_id, str) or not tz_id:
                    raise StoreError("VTIMEZONE missing non-empty string tz_id")
                if not any(
                    c.get("type") == "VTIMEZONE" and c.get("tz_id") == tz_id
                    for c in self.components
                ):
                    self.components.append({"type": "VTIMEZONE", "tz_id": tz_id})
            else:
                canon = canonicalize_component(raw_comp, is_add=False)
                validate_component_state(canon, allow_legacy=True)
                self._validate_uid_override_alignment(canon, require_main=False)
                self._ensure_unique_identity(canon["uid"], canon["recurrence_id"])
                self.components.append(canon)
                self._register_comp_timezones(canon)

    _normalize_range = staticmethod(normalize_range)
    _is_parent_relation = staticmethod(is_parent_relation)
    _validate_related_to = staticmethod(validate_related_to)
    _validate_component_state = staticmethod(validate_component_state)
    _align_rrule_until_on_dtstart_change = staticmethod(
        align_rrule_until_on_dtstart_change
    )
    _filter_valid_exdates = staticmethod(filter_valid_exdates)
    _compute_duration = staticmethod(compute_component_duration)
    _shift_comp_end_or_due = staticmethod(shift_comp_end_or_due)
    _shift_override_in_place = staticmethod(shift_override_in_place)

    def _canonicalize_component(
        self,
        comp: dict[str, Any],
        *,
        is_add: bool,
        default_type: str | None = None,
        now: str = DEFAULT_DTSTAMP,
    ) -> dict[str, Any]:
        return canonicalize_component(
            comp, is_add=is_add, default_type=default_type, now=now
        )

    def _validate_uid_override_alignment(
        self, comp: dict[str, Any], *, require_main: bool = False
    ) -> None:
        """Ensure override RECURRENCE-ID and DTSTART align with main DTSTART (R-L1-007, I-K-003..007)."""
        uid = comp["uid"]
        is_ov = (
            comp.get("recurrence_id") is not None
            and not comp.get("rrule")
            and not comp.get("rdate")
        )
        if is_ov:
            main = next(
                (
                    c
                    for c in self.components
                    if c.get("type") != "VTIMEZONE"
                    and c.get("uid") == uid
                    and c.get("recurrence_id") is None
                ),
                None,
            )
            if main is None:
                if require_main:
                    raise StoreError(
                        f"Override on uid={uid!r} has no main component (I-K-003)"
                    )
                return
            _check_override_pair(comp, main, check_candidate=require_main)
            return
        if comp.get("recurrence_id") is None and comp.get("dtstart"):
            for ov in self.components:
                if (
                    ov is not comp
                    and ov.get("type") != "VTIMEZONE"
                    and ov.get("uid") == uid
                    and ov.get("recurrence_id") is not None
                    and not ov.get("rrule")
                    and not ov.get("rdate")
                ):
                    _check_override_pair(ov, comp, check_candidate=False)

    def _ensure_unique_identity(
        self,
        uid: str,
        canon_rid: str | None,
        ignore_comp: dict[str, Any] | None = None,
    ) -> None:
        """Raise StoreError if another component already has the same (uid, recurrence_id)."""
        main = next(
            (
                c
                for c in self.components
                if c.get("type") != "VTIMEZONE"
                and c.get("uid") == uid
                and c.get("recurrence_id") is None
            ),
            None,
        )
        pt_main = (
            parse_temporal(main["dtstart"], "dtstart")
            if main is not None and main.get("dtstart")
            else None
        )
        norm_new = (
            format_canonical_rid(align_rid_to_master(canon_rid, pt_main))
            if canon_rid is not None and pt_main is not None
            else canon_rid
        )
        for existing in self.components:
            if (
                existing is ignore_comp
                or existing.get("type") == "VTIMEZONE"
                or existing.get("uid") != uid
            ):
                continue
            ex_rid = existing.get("recurrence_id")
            norm_ex = (
                format_canonical_rid(align_rid_to_master(ex_rid, pt_main))
                if ex_rid is not None and pt_main is not None
                else ex_rid
            )
            if ex_rid == canon_rid or norm_ex == norm_new:
                raise StoreError(
                    f"Duplicate component identity (uid={uid!r}, recurrence_id={canon_rid!r})"
                )

    def _register_comp_timezones(self, comp: dict[str, Any]) -> None:
        """Register VTIMEZONE components for TZID-qualified temporal properties (R-L5-005, R-L5-006)."""
        raw_values = [comp.get(f) for f in ("dtstart", "dtend", "due", "recurrence_id")]
        raw_values.extend(comp.get("rdate") or ())
        raw_values.extend(comp.get("exdate") or ())
        for raw_dt in raw_values:
            if not raw_dt:
                continue
            pt = parse_temporal(raw_dt, "temporal")
            if pt.kind == "TZID" and pt.tzid:
                if not any(
                    c.get("type") == "VTIMEZONE" and c.get("tz_id") == pt.tzid
                    for c in self.components
                ):
                    vtz_idx = sum(
                        1 for c in self.components if c.get("type") == "VTIMEZONE"
                    )
                    self.components.insert(
                        vtz_idx, {"type": "VTIMEZONE", "tz_id": pt.tzid}
                    )

    def _partition_uid_components(
        self, uid: str
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, Any] | None,
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Return (uid_comps, master_comp, recurring_segments, standalone_overrides)."""
        uid_comps = [
            c
            for c in self.components
            if c.get("type") != "VTIMEZONE" and c.get("uid") == uid
        ]
        master_comp = next(
            (c for c in uid_comps if c.get("recurrence_id") is None), None
        )
        recurring_segments = [
            c
            for c in uid_comps
            if c.get("rrule") or c.get("rdate") or c.get("recurrence_id") is None
        ]
        standalone_overrides = [
            c
            for c in uid_comps
            if c.get("recurrence_id") is not None
            and not c.get("rrule")
            and not c.get("rdate")
        ]
        return uid_comps, master_comp, recurring_segments, standalone_overrides

    @staticmethod
    def _reject_legacy_segments(uid_comps: list[dict[str, Any]]) -> None:
        """Refuse writes on a UID holding legacy shared-UID segments (R-L3-009 open question)."""
        if any(
            c.get("recurrence_id") is not None and (c.get("rrule") or c.get("rdate"))
            for c in uid_comps
        ):
            raise StoreError(
                "Write on a UID with legacy shared-UID segments (RECURRENCE-ID plus "
                "RRULE/RDATE) is unspecified (R-L3-009)"
            )

    @staticmethod
    def _is_first_instance_split(
        recurrence_id: str | None,
        norm_range: str,
        master_comp: dict[str, Any] | None,
    ) -> bool:
        """Return True if a THIS_AND_FUTURE operation targets the earliest candidate occurrence."""
        if (
            recurrence_id is None
            or norm_range != "THIS_AND_FUTURE"
            or master_comp is None
            or not master_comp.get("dtstart")
            or not (master_comp.get("rrule") or master_comp.get("rdate"))
        ):
            return False
        pt_m = parse_temporal(master_comp["dtstart"], "dtstart")
        cands = expand_component_candidates(master_comp, include_exdates=True)
        if not cands:
            return False
        return (
            format_canonical_rid(align_rid_to_master(recurrence_id, pt_m))
            == cands[0][0]
        )

    def _truncate_segment_before(
        self,
        target_seg: dict[str, Any],
        pt_split: ParsedTemporal,
        pt_seg_start: ParsedTemporal,
        split_cmp: datetime.datetime,
        eff_now: str,
        *,
        has_surviving_overrides: bool = False,
    ) -> None:
        """Truncate target_seg strictly before pt_split and bump revision metadata."""
        truncate_segment_terms(
            target_seg,
            pt_split,
            pt_seg_start,
            split_cmp,
            has_surviving_overrides=has_surviving_overrides,
        )
        self._bump_revision_metadata(target_seg, eff_now)

    @staticmethod
    def _bump_revision_metadata(comp: dict[str, Any], eff_now: str) -> None:
        """Increment sequence and monotonically update dtstamp and last_modified (I-T-005, I-T-006)."""
        old_seq = comp.get("sequence") or 0
        comp["sequence"] = old_seq + 1 if old_seq else 1
        mono_now = max_utc_timestamp(
            eff_now, comp.get("dtstamp"), comp.get("last_modified")
        )
        comp["dtstamp"] = mono_now
        comp["last_modified"] = mono_now

    @classmethod
    def _apply_in_place_edit_metadata(cls, comp: dict[str, Any], eff_now: str) -> None:
        """Ensure created is initialized and bump revision metadata on an edited component."""
        comp["created"] = comp.get("created") or comp.get("dtstamp") or eff_now
        cls._bump_revision_metadata(comp, eff_now)

    @staticmethod
    def _update_todo_completed(
        comp: dict[str, Any],
        patch: dict[str, Any],
        old_status: str | None,
        old_completed: str | None,
        eff_now: str,
    ) -> None:
        """Maintain VTODO COMPLETED timestamp transitions (R-L5-004)."""
        if comp.get("type") != "VTODO":
            return
        if "status" in patch and "completed" not in patch:
            new_status = patch["status"]
            if old_status != "COMPLETED" and new_status == "COMPLETED":
                comp["completed"] = eff_now
            elif old_completed is not None and new_status != "COMPLETED":
                comp["completed"] = None
            elif old_status == "COMPLETED" and new_status == "COMPLETED":
                comp["completed"] = old_completed

    @staticmethod
    def _find_segment_for_rid(
        recurring_segments: list[dict[str, Any]],
        recurrence_id: str,
        *,
        include_exdates: bool,
    ) -> dict[str, Any] | None:
        """Return the recurring segment whose candidate/active set contains recurrence_id."""
        true_recurring = [
            s for s in recurring_segments if s.get("rrule") or s.get("rdate")
        ]
        ordered = sorted(
            true_recurring,
            key=lambda s: parse_temporal(s["dtstart"], "dtstart").dt_utc_or_naive,
            reverse=True,
        )
        for seg in ordered:
            pt_s = parse_temporal(seg["dtstart"], "dtstart")
            canon_target = format_canonical_rid(
                align_rid_to_master(recurrence_id, pt_s)
            )
            cand_rids = {
                rid
                for rid, _, _ in expand_component_candidates(
                    seg, include_exdates=include_exdates
                )
            }
            if canon_target in cand_rids:
                return seg
        return None

    @staticmethod
    def _find_override_for_rid(
        standalone_overrides: list[dict[str, Any]],
        recurrence_id: str,
        ref_pt: ParsedTemporal | None,
    ) -> dict[str, Any] | None:
        """Find an existing standalone override matching recurrence_id."""
        pt_target = (
            align_rid_to_master(recurrence_id, ref_pt)
            if ref_pt is not None
            else parse_temporal(recurrence_id, "recurrence_id")
        )
        canon_target = format_canonical_rid(pt_target)
        for ov in standalone_overrides:
            ov_pt = (
                align_rid_to_master(ov["recurrence_id"], ref_pt)
                if ref_pt is not None
                else parse_temporal(ov["recurrence_id"], "recurrence_id")
            )
            if format_canonical_rid(ov_pt) == canon_target:
                return ov
        return None

    def _should_shift_series_exceptions(
        self,
        patch: dict[str, Any],
        pt_old_start: ParsedTemporal | None,
        pt_new_start: ParsedTemporal,
        normalized_from_first_instance: bool,
    ) -> datetime.timedelta:
        """Return wall-clock shift delta when SHIFT_WITH_SERIES applies, else 0."""
        if (
            self.policy.series_reschedule_exception_mode
            == SeriesRescheduleExceptionMode.SHIFT_WITH_SERIES
            and not normalized_from_first_instance
            and "dtstart" in patch
            and "rrule" not in patch
            and pt_old_start is not None
            and temporal_class(pt_old_start) == temporal_class(pt_new_start)
        ):
            return compute_wall_clock_delta(pt_old_start, pt_new_start)
        return datetime.timedelta(0)
