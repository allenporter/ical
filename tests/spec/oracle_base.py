"""Clean-room Base Store Class and Segment/Override Helpers for ReferenceStore.

Implements shared metadata lifecycle (R-L5-001..R-L5-003), VTIMEZONE registration
(R-L5-005, R-L5-006), candidate-based segment lookup (R-L3-006), and DST-safe
duration/truncation/shift helpers (R-L3-003, R-L4-004, R-L4-005).
"""

from __future__ import annotations

import datetime
from typing import Any

from .oracle_canonical import (
    DEFAULT_DTSTAMP,
    align_rrule_until_on_dtstart_change,
    canonicalize_component,
    is_parent_relation,
    normalize_range,
    validate_component_state,
    validate_related_to,
)
from .oracle_policy import (
    PolicyConfig,
    SeriesRescheduleExceptionMode,
    StoreError,
)
from .oracle_temporal import (
    ParsedTemporal,
    add_temporal_duration,
    align_rid_to_master,
    compute_temporal_duration,
    compute_until_string,
    compute_wall_clock_delta,
    expand_component_candidates,
    format_canonical_rid,
    format_temporal_like,
    parse_temporal,
    replace_rrule_until,
    shift_wall_clock,
    temporal_class,
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
                if not tz_id:
                    raise StoreError("VTIMEZONE missing tz_id")
                if not any(
                    c.get("type") == "VTIMEZONE" and c.get("tz_id") == tz_id
                    for c in self.components
                ):
                    self.components.append({"type": "VTIMEZONE", "tz_id": tz_id})
            else:
                canon = canonicalize_component(raw_comp, is_add=False)
                validate_component_state(canon)
                self._ensure_unique_identity(canon["uid"], canon["recurrence_id"])
                self.components.append(canon)
                # Loaded state must satisfy I-K-006 (RFC 5545 Section 3.2.19) too.
                self._register_comp_timezones(canon)

    _normalize_range = staticmethod(normalize_range)
    _is_parent_relation = staticmethod(is_parent_relation)
    _validate_related_to = staticmethod(validate_related_to)
    _validate_component_state = staticmethod(validate_component_state)

    def _canonicalize_component(
        self,
        comp: dict[str, Any],
        *,
        is_add: bool,
        default_type: str | None = None,
        now: str = DEFAULT_DTSTAMP,
    ) -> dict[str, Any]:
        """Delegate canonical dictionary normalization to oracle_canonical."""
        return canonicalize_component(
            comp, is_add=is_add, default_type=default_type, now=now
        )

    def _ensure_unique_identity(
        self,
        uid: str,
        canon_rid: str | None,
        ignore_comp: dict[str, Any] | None = None,
    ) -> None:
        """Raise StoreError if another component already has the same (uid, recurrence_id)."""
        for existing in self.components:
            if (
                existing is not ignore_comp
                and existing.get("type") != "VTIMEZONE"
                and existing.get("uid") == uid
                and existing.get("recurrence_id") == canon_rid
            ):
                raise StoreError(
                    f"Duplicate component identity (uid={uid!r}, recurrence_id={canon_rid!r})"
                )

    def _register_comp_timezones(self, comp: dict[str, Any]) -> None:
        """Register VTIMEZONE components for TZID-qualified dtstart, dtend, and due (R-L5-005, R-L5-006)."""
        for field in ("dtstart", "dtend", "due"):
            raw_dt = comp.get(field)
            if not raw_dt:
                continue
            pt = parse_temporal(raw_dt, field)
            if pt.kind == "OFFSET":
                raise StoreError(
                    f"Fixed-offset datetime without IANA TZID cannot be registered as VTIMEZONE: {raw_dt!r}"
                )
            if pt.kind == "TZID" and pt.tzid:
                has_vtz = any(
                    c.get("type") == "VTIMEZONE" and c.get("tz_id") == pt.tzid
                    for c in self.components
                )
                if not has_vtz:
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
    def _is_first_instance_split(
        recurrence_id: str | None,
        norm_range: str,
        master_comp: dict[str, Any] | None,
    ) -> bool:
        """Return True if a THIS_AND_FUTURE operation targets a recurring master's first occurrence."""
        if (
            recurrence_id is None
            or norm_range != "THIS_AND_FUTURE"
            or master_comp is None
            or not master_comp.get("dtstart")
            or not (master_comp.get("rrule") or master_comp.get("rdate"))
        ):
            return False
        pt_m = parse_temporal(master_comp["dtstart"], "dtstart")
        return format_canonical_rid(
            align_rid_to_master(recurrence_id, pt_m)
        ) == format_canonical_rid(pt_m)

    @staticmethod
    def _filter_valid_exdates(comp: dict[str, Any]) -> list[str]:
        """Filter a component's exdate list against its unexcluded candidate set (R-L1-004, R-L4-004)."""
        if not (comp.get("rrule") or comp.get("rdate")) or not comp.get("exdate"):
            return []
        pt_start = parse_temporal(comp["dtstart"], "dtstart")
        valid_rids = {
            rid for rid, _, _ in expand_component_candidates(comp, include_exdates=True)
        }
        kept: list[str] = []
        for ex_raw in comp["exdate"]:
            pt_ex = parse_temporal(ex_raw, "exdate")
            if temporal_class(pt_ex) != temporal_class(pt_start):
                continue
            if (
                format_canonical_rid(align_rid_to_master(ex_raw, pt_start))
                in valid_rids
            ):
                kept.append(ex_raw)
        return kept

    def _truncate_segment_before(
        self,
        target_seg: dict[str, Any],
        pt_split: ParsedTemporal,
        pt_seg_start: ParsedTemporal,
        split_cmp: datetime.datetime,
        eff_now: str,
    ) -> None:
        """Truncate target_seg strictly before pt_split and update its revision metadata."""
        if target_seg.get("rrule"):
            until_str = compute_until_string(pt_split, pt_seg_start)
            target_seg["rrule"] = replace_rrule_until(target_seg["rrule"], until_str)
        if target_seg.get("rdate"):
            target_seg["rdate"] = [
                rd
                for rd in target_seg["rdate"]
                if align_rid_to_master(rd, pt_seg_start).dt_utc_or_naive < split_cmp
            ]
        target_seg["exdate"] = self._filter_valid_exdates(target_seg)
        self._bump_revision_metadata(target_seg, eff_now)

    _align_rrule_until_on_dtstart_change = staticmethod(
        align_rrule_until_on_dtstart_change
    )

    @staticmethod
    def _compute_duration(comp: dict[str, Any]) -> datetime.timedelta | None:
        """Compute physical elapsed duration of comp across DST transitions."""
        dtstart_raw = comp.get("dtstart")
        end_raw = comp.get("dtend") or comp.get("due")
        if not dtstart_raw or not end_raw:
            return None
        pt_s = parse_temporal(dtstart_raw, "dtstart")
        pt_e = parse_temporal(end_raw, "dtend/due")
        if pt_s.is_date != pt_e.is_date:
            return None
        return compute_temporal_duration(pt_s, pt_e)

    @staticmethod
    def _shift_comp_end_or_due(
        comp: dict[str, Any],
        patch: dict[str, Any],
        orig_dur: datetime.timedelta | None,
    ) -> None:
        """Shift dtend/due on comp using DST-safe physical duration when dtstart changes."""
        if (
            "dtstart" not in patch
            or "dtend" in patch
            or "due" in patch
            or orig_dur is None
            or not comp.get("dtstart")
        ):
            return
        end_key = "due" if comp.get("type") == "VTODO" else "dtend"
        if comp.get(end_key) is None:
            return
        pt_ns = parse_temporal(comp["dtstart"], "dtstart")
        min_days = 0 if end_key == "due" else 1
        new_end_v = add_temporal_duration(pt_ns.value, orig_dur, min_days=min_days)
        comp[end_key] = format_temporal_like(new_end_v, pt_ns)

    @staticmethod
    def _bump_revision_metadata(comp: dict[str, Any], eff_now: str) -> None:
        """Increment sequence and update dtstamp and last_modified (preserving created)."""
        old_seq = comp.get("sequence") or 0
        comp["sequence"] = old_seq + 1 if old_seq else 1
        comp["dtstamp"] = eff_now
        comp["last_modified"] = eff_now

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
    def _segment_cutoff_cmp(
        target_seg: dict[str, Any],
        pt_seg_start: ParsedTemporal,
        split_cmp: datetime.datetime,
        is_seg_start: bool,
    ) -> datetime.datetime:
        """Compute UTC/naive cutoff comparison timestamp for overrides/downstream segments."""
        cutoff_cmp = split_cmp
        if is_seg_start:
            cutoff_cmp = min(cutoff_cmp, pt_seg_start.dt_utc_or_naive)
            if target_seg.get("recurrence_id") is not None:
                cutoff_cmp = min(
                    cutoff_cmp,
                    align_rid_to_master(
                        target_seg["recurrence_id"], pt_seg_start
                    ).dt_utc_or_naive,
                )
        return cutoff_cmp

    @staticmethod
    def _targets_seg_start(seg: dict[str, Any], recurrence_id: str) -> bool:
        """Return True if recurrence_id targets the starting occurrence of seg."""
        pt_seg_start = parse_temporal(seg["dtstart"], "dtstart")
        canon_split = format_canonical_rid(
            align_rid_to_master(recurrence_id, pt_seg_start)
        )
        if canon_split == format_canonical_rid(pt_seg_start):
            return True
        if seg.get("recurrence_id") is not None:
            return canon_split == format_canonical_rid(
                align_rid_to_master(seg["recurrence_id"], pt_seg_start)
            )
        return False

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
        if not true_recurring:
            return None
        if include_exdates:
            for seg in true_recurring:
                if seg.get("recurrence_id") is not None:
                    pt_s = parse_temporal(seg["dtstart"], "dtstart")
                    if format_canonical_rid(
                        align_rid_to_master(recurrence_id, pt_s)
                    ) == format_canonical_rid(
                        align_rid_to_master(seg["recurrence_id"], pt_s)
                    ):
                        return seg
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

    @staticmethod
    def _shift_override_in_place(
        ov: dict[str, Any],
        wall_delta: datetime.timedelta,
        pt_old_ref: ParsedTemporal,
        pt_new_ref: ParsedTemporal,
    ) -> None:
        """Shift an override component's recurrence_id, dtstart, and dtend/due in wall-clock time."""
        if not wall_delta:
            return
        pt_rid = align_rid_to_master(ov["recurrence_id"], pt_old_ref)
        shifted_rid_str = format_temporal_like(
            shift_wall_clock(pt_rid.value, wall_delta), pt_new_ref
        )
        ov["recurrence_id"] = format_canonical_rid(
            parse_temporal(shifted_rid_str, "recurrence_id")
        )
        if ov.get("dtstart"):
            orig_dur = OracleBase._compute_duration(ov)
            pt_ov_s = parse_temporal(ov["dtstart"], "dtstart")
            ov["dtstart"] = format_temporal_like(
                shift_wall_clock(pt_ov_s.value, wall_delta), pt_ov_s
            )
            pt_ov_ns = parse_temporal(ov["dtstart"], "dtstart")
            for end_k in ("dtend", "due"):
                if ov.get(end_k) is not None and orig_dur is not None:
                    min_days = 0 if end_k == "due" else 1
                    ov[end_k] = format_temporal_like(
                        add_temporal_duration(
                            pt_ov_ns.value, orig_dur, min_days=min_days
                        ),
                        pt_ov_ns,
                    )

    def _collect_next_linked_uids(self, start_comp: dict[str, Any]) -> list[str]:
        """Follow outgoing RELTYPE=NEXT links transitively from start_comp."""
        chain: list[str] = []
        visited: set[str] = {start_comp["uid"]}
        frontier = [
            str(r["uid"])
            for r in (start_comp.get("related_to") or [])
            if str(r.get("reltype") or "").upper() == "NEXT" and r.get("uid")
        ]
        while frontier:
            nxt_uid = frontier.pop(0)
            if nxt_uid in visited:
                continue
            visited.add(nxt_uid)
            chain.append(nxt_uid)
            for comp in self.components:
                if comp.get("type") != "VTIMEZONE" and comp.get("uid") == nxt_uid:
                    frontier.extend(
                        str(r["uid"])
                        for r in (comp.get("related_to") or [])
                        if str(r.get("reltype") or "").upper() == "NEXT"
                        and r.get("uid")
                    )
        return chain

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
            and pt_old_start.is_date == pt_new_start.is_date
        ):
            return compute_wall_clock_delta(pt_old_start, pt_new_start)
        return datetime.timedelta(0)
