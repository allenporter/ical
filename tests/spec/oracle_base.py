"""Clean-room Base Store Class and Component/Segment Helpers for ReferenceStore.

Implements shared metadata lifecycle (R-L5-001, R-L5-002, R-L5-003), timezone
validation (R-L5-004, R-L5-005, R-L5-006), relation validation (R-L5-007, R-L5-008),
and segment truncation (R-L3-003, R-L3-007) for `ReferenceStore`.
"""

from __future__ import annotations

import copy
import datetime
from typing import Any

from .oracle_temporal import (
    ParsedTemporal,
    PolicyConfig,
    SeriesRescheduleExceptionMode,
    SplitFutureOverrideMode,
    StoreError,
    align_rid_to_master,
    compute_until_string,
    expand_component_candidates,
    format_canonical_rid,
    format_temporal_like,
    parse_temporal,
    replace_rrule_until,
)


class OracleBase:
    """Base class providing state and shared component/segment helpers for ReferenceStore."""

    def __init__(
        self,
        initial_components: list[dict[str, Any]] | None = None,
        policy: PolicyConfig | None = None,
        track_vtimezone: bool | None = None,
    ) -> None:
        self.policy = policy or PolicyConfig()
        self.components: list[dict[str, Any]] = copy.deepcopy(initial_components or [])
        if track_vtimezone is None:
            self.track_vtimezone = len(self.components) == 0 or any(
                c.get("type") == "VTIMEZONE" for c in self.components
            )
        else:
            self.track_vtimezone = track_vtimezone
        self._split_counter = 0

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
        """Return True if a THIS_AND_FUTURE operation targets the master's first occurrence."""
        if (
            recurrence_id is None
            or norm_range != "THIS_AND_FUTURE"
            or master_comp is None
            or not master_comp.get("dtstart")
        ):
            return False
        pt_m = parse_temporal(master_comp["dtstart"], "dtstart")
        return format_canonical_rid(
            align_rid_to_master(recurrence_id, pt_m)
        ) == format_canonical_rid(pt_m)

    @staticmethod
    def _is_parent_relation(rel: dict[str, Any]) -> bool:
        """Return True if a RELATED-TO entry is a PARENT relationship (R-L5-007, R-L5-009)."""
        reltype = str(rel.get("reltype") or "PARENT").upper()
        return reltype not in ("CHILD", "SIBLING", "SIBBLING", "NEXT", "FIRST")

    @staticmethod
    def _validate_related_to(comp_or_patch: dict[str, Any]) -> None:
        """Validate RELATED-TO property constraints, accepting all RELTYPE values (R-L5-009)."""
        for rel in comp_or_patch.get("related_to") or ():
            if not rel.get("uid"):
                raise StoreError("RELATED-TO entry missing uid (R-L5-009)")

    def _validate_and_register_timezone(
        self, raw_dt: str | None, field_name: str
    ) -> ParsedTemporal | None:
        """Validate temporal value and register VTIMEZONE if TZID-qualified (R-L5-005, R-L5-006)."""
        if raw_dt is None:
            return None
        pt = parse_temporal(raw_dt, field_name)
        if pt.kind == "OFFSET":
            raise StoreError(
                f"Fixed-offset datetime without IANA TZID cannot be registered as VTIMEZONE: {raw_dt!r} (R-L5-005, R-L5-006)"
            )
        if pt.kind == "TZID" and pt.tzid and self.track_vtimezone:
            has_vtz = any(
                c.get("type") == "VTIMEZONE" and c.get("tz_id") == pt.tzid
                for c in self.components
            )
            if not has_vtz:
                vtz_idx = sum(
                    1 for c in self.components if c.get("type") == "VTIMEZONE"
                )
                self.components.insert(vtz_idx, {"type": "VTIMEZONE", "tz_id": pt.tzid})
        return pt

    @staticmethod
    def _filter_valid_exdates(comp: dict[str, Any]) -> list[str]:
        """Filter a component's exdate list against its unexcluded candidate set (R-L1-007, R-L4-004)."""
        if not (comp.get("rrule") or comp.get("rdate")) or not comp.get("exdate"):
            return []
        pt_start = parse_temporal(comp["dtstart"], "dtstart")
        valid_rids = {
            rid for rid, _, _ in expand_component_candidates(comp, include_exdates=True)
        }
        return [
            ex_raw
            for ex_raw in comp["exdate"]
            if (pt_ex := parse_temporal(ex_raw, "exdate")).is_date == pt_start.is_date
            and pt_ex.kind == pt_start.kind
            and format_canonical_rid(pt_ex) in valid_rids
        ]

    def _truncate_segment_before(
        self,
        target_seg: dict[str, Any],
        pt_split: ParsedTemporal,
        pt_seg_start: ParsedTemporal,
        split_cmp: datetime.datetime,
    ) -> None:
        """Truncate target_seg's rrule, rdate, and exdate strictly before pt_split."""
        if target_seg.get("rrule"):
            until_str = compute_until_string(pt_split, pt_seg_start)
            target_seg["rrule"] = replace_rrule_until(target_seg["rrule"], until_str)
        if target_seg.get("rdate"):
            target_seg["rdate"] = [
                rd
                for rd in target_seg["rdate"]
                if parse_temporal(rd, "rdate").dt_utc_or_naive < split_cmp
            ]
        if "exdate" in target_seg:
            target_seg["exdate"] = self._filter_valid_exdates(target_seg)

    @staticmethod
    def _align_rrule_until_on_dtstart_change(
        comp: dict[str, Any],
        pt_old_start: ParsedTemporal | None,
        pt_new_start: ParsedTemporal,
    ) -> None:
        """Align RRULE UNTIL value type and timezone form when DTSTART changes (R-L1-003, R-L1-007)."""
        rrule_parts = dict(
            p.split("=", 1) for p in comp["rrule"].split(";") if "=" in p
        )
        pt_u = parse_temporal(rrule_parts["UNTIL"], "until")
        if pt_new_start.is_date and not pt_u.is_date:
            assert isinstance(pt_u.value, datetime.datetime)
            comp["rrule"] = replace_rrule_until(
                comp["rrule"], pt_u.value.date().strftime("%Y%m%d")
            )
        elif not pt_new_start.is_date and pt_u.is_date:
            assert isinstance(pt_new_start.value, datetime.datetime)
            comb_dt = datetime.datetime.combine(pt_u.value, pt_new_start.value.time())
            if pt_new_start.value.tzinfo is not None:
                comb_dt = comb_dt.replace(tzinfo=pt_new_start.value.tzinfo).astimezone(
                    datetime.timezone.utc
                )
                new_u_str = comb_dt.strftime("%Y%m%dT%H%M%SZ")
            else:
                new_u_str = comb_dt.strftime("%Y%m%dT%H%M%S")
            comp["rrule"] = replace_rrule_until(comp["rrule"], new_u_str)
        elif not pt_new_start.is_date and not pt_u.is_date:
            assert isinstance(pt_new_start.value, datetime.datetime)
            assert isinstance(pt_u.value, datetime.datetime)
            if pt_new_start.value.tzinfo is not None and pt_u.value.tzinfo is None:
                comb_dt = pt_u.value.replace(
                    tzinfo=pt_new_start.value.tzinfo
                ).astimezone(datetime.timezone.utc)
                comp["rrule"] = replace_rrule_until(
                    comp["rrule"], comb_dt.strftime("%Y%m%dT%H%M%SZ")
                )
            elif pt_new_start.value.tzinfo is None and pt_u.value.tzinfo is not None:
                ref_tz = (
                    pt_old_start.value.tzinfo
                    if (
                        pt_old_start
                        and isinstance(pt_old_start.value, datetime.datetime)
                    )
                    else None
                )
                local_u = (
                    pt_u.value.astimezone(ref_tz).replace(tzinfo=None)
                    if ref_tz
                    else pt_u.value.replace(tzinfo=None)
                )
                comp["rrule"] = replace_rrule_until(
                    comp["rrule"], local_u.strftime("%Y%m%dT%H%M%S")
                )

    @staticmethod
    def _shift_comp_end_or_due(
        comp: dict[str, Any],
        patch: dict[str, Any],
        orig_dur: datetime.timedelta | None,
    ) -> None:
        """Shift dtend/due on comp to preserve orig_dur when dtstart changes."""
        if (
            "dtstart" not in patch
            or "dtend" in patch
            or "due" in patch
            or orig_dur is None
            or not comp.get("dtstart")
        ):
            return
        end_key = "due" if "due" in comp else "dtend"
        if end_key not in comp:
            return
        pt_ns = parse_temporal(comp["dtstart"], "dtstart")
        if pt_ns.is_date and not isinstance(pt_ns.value, datetime.datetime):
            min_days = 0 if end_key == "due" else 1
            new_end_v: datetime.date | datetime.datetime = (
                pt_ns.value + datetime.timedelta(days=max(min_days, orig_dur.days))
            )
        else:
            new_end_v = pt_ns.value + orig_dur
        comp[end_key] = format_temporal_like(new_end_v, pt_ns)

    def _copy_inherited_metadata(
        self,
        dest: dict[str, Any],
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        now: str | None,
    ) -> None:
        """Copy summary and non-schedule properties from target_seg + patch into dest."""
        dest["summary"] = patch.get("summary", target_seg.get("summary"))
        for k in ("location", "description", "status", "completed", "related_to"):
            if k in patch or k in target_seg:
                dest[k] = patch.get(k, copy.deepcopy(target_seg.get(k)))
        self._update_todo_completed(
            dest, patch, target_seg.get("status"), target_seg.get("completed"), now
        )

    @staticmethod
    def _compute_duration(comp: dict[str, Any]) -> datetime.timedelta | None:
        dtstart_raw, end_raw = (
            comp.get("dtstart"),
            comp.get("dtend") or comp.get("due"),
        )
        if not dtstart_raw or not end_raw:
            return None
        pt_s, pt_e = (
            parse_temporal(dtstart_raw, "dtstart"),
            parse_temporal(end_raw, "dtend/due"),
        )
        if pt_s.is_date and pt_e.is_date:
            return pt_e.value - pt_s.value  # type: ignore[operator]
        if isinstance(pt_s.value, datetime.datetime) and isinstance(
            pt_e.value, datetime.datetime
        ):
            return pt_e.value - pt_s.value
        return None

    @staticmethod
    def _insert_key_after(
        d: dict[str, Any], after_key: str, new_key: str, new_val: Any
    ) -> None:
        items = list(d.items())
        d.clear()
        inserted = False
        for k, v in items:
            d[k] = v
            if k == after_key and not inserted:
                d[new_key] = new_val
                inserted = True
        if not inserted:
            d[new_key] = new_val

    @staticmethod
    def _update_edit_metadata(
        comp: dict[str, Any], patch: dict[str, Any], now: str | None
    ) -> None:
        if "sequence" in comp or "dtstamp" in comp or now is not None:
            old_seq = comp.get("sequence") or 0
            comp["sequence"] = old_seq + 1 if old_seq else 1
        if "dtstamp" in comp or now is not None:
            eff_now = patch.get("dtstamp") or now or comp.get("dtstamp")
            comp["dtstamp"] = eff_now
            comp["last_modified"] = eff_now

    @staticmethod
    def _update_todo_completed(
        comp: dict[str, Any],
        patch: dict[str, Any],
        old_status: str | None,
        old_completed: str | None,
        now: str | None,
    ) -> None:
        if "status" in patch and "completed" not in patch:
            new_status = patch["status"]
            eff_now = (
                patch.get("dtstamp")
                or now
                or comp.get("dtstamp")
                or "2025-01-01T00:00:00Z"
            )
            if old_status != "COMPLETED" and new_status == "COMPLETED":
                comp["completed"] = eff_now
            elif old_completed is not None and new_status != "COMPLETED":
                comp["completed"] = None
            elif old_status == "COMPLETED" and new_status == "COMPLETED":
                comp["completed"] = old_completed
        if "dtstamp" in patch and "dtstamp" not in comp:
            comp.pop("dtstamp", None)

    @staticmethod
    def _segment_cutoff_cmp(
        target_seg: dict[str, Any],
        pt_seg_start: ParsedTemporal,
        split_cmp: datetime.datetime,
        is_seg_start: bool,
    ) -> datetime.datetime:
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
        recurring_segments: list[dict[str, Any]], recurrence_id: str
    ) -> dict[str, Any] | None:
        if not recurring_segments:
            return None
        if len(recurring_segments) == 1:
            return recurring_segments[0]
        for seg in recurring_segments:
            if seg.get("recurrence_id") is not None:
                pt_s = parse_temporal(seg["dtstart"], "dtstart")
                if format_canonical_rid(
                    align_rid_to_master(recurrence_id, pt_s)
                ) == format_canonical_rid(
                    align_rid_to_master(seg["recurrence_id"], pt_s)
                ):
                    return seg
        seg_with_start = sorted(
            [
                (
                    (pt_s := parse_temporal(seg["dtstart"], "dtstart")).dt_utc_or_naive,
                    seg,
                    pt_s,
                )
                for seg in recurring_segments
            ],
            key=lambda t: t[0],
            reverse=True,
        )
        for seg_start_dt, seg, pt_s in seg_with_start:
            if align_rid_to_master(recurrence_id, pt_s).dt_utc_or_naive >= seg_start_dt:
                return seg
        return seg_with_start[-1][1]

    @staticmethod
    def _shift_override_in_place(
        ov: dict[str, Any],
        delta: datetime.timedelta,
        pt_old_ref: ParsedTemporal,
        pt_new_ref: ParsedTemporal,
    ) -> None:
        """Shift an override component's recurrence_id, dtstart, and dtend/due by delta."""
        if not delta:
            return
        pt_rid = align_rid_to_master(ov["recurrence_id"], pt_old_ref)
        shifted_rid_str = format_temporal_like(pt_rid.value + delta, pt_new_ref)
        ov["recurrence_id"] = format_canonical_rid(
            parse_temporal(shifted_rid_str, "recurrence_id")
        )
        if ov.get("dtstart"):
            pt_ov_s = parse_temporal(ov["dtstart"], "dtstart")
            ov["dtstart"] = format_temporal_like(pt_ov_s.value + delta, pt_ov_s)
        for end_k in ("dtend", "due"):
            if ov.get(end_k):
                pt_ov_e = parse_temporal(ov[end_k], end_k)
                ov[end_k] = format_temporal_like(pt_ov_e.value + delta, pt_ov_e)

    def _should_shift_series_exceptions(
        self,
        patch: dict[str, Any],
        pt_old_start: ParsedTemporal | None,
        pt_new_start: ParsedTemporal,
        normalized_from_first_instance: bool,
    ) -> datetime.timedelta:
        """Return the series shift timedelta if SHIFT_WITH_SERIES applies, else 0."""
        if (
            self.policy.series_reschedule_exception_mode
            == SeriesRescheduleExceptionMode.SHIFT_WITH_SERIES
            and not normalized_from_first_instance
            and "dtstart" in patch
            and pt_old_start is not None
            and pt_old_start.is_date == pt_new_start.is_date
        ):
            return pt_new_start.value - pt_old_start.value
        return datetime.timedelta(0)

    def _handle_split_future_overrides(
        self,
        uid_comps: list[dict[str, Any]],
        target_seg: dict[str, Any],
        future_comp: dict[str, Any],
        pt_seg_start: ParsedTemporal,
        pt_split: ParsedTemporal,
        cutoff_cmp: datetime.datetime,
    ) -> None:
        """Discard or migrate standalone overrides at/after cutoff_cmp on THIS_AND_FUTURE edit."""
        if self.policy.split_future_override_mode == SplitFutureOverrideMode.DISCARD:
            for c in list(uid_comps):
                if c is not target_seg and c.get("recurrence_id") is not None:
                    if (
                        align_rid_to_master(
                            c["recurrence_id"], pt_seg_start
                        ).dt_utc_or_naive
                        >= cutoff_cmp
                    ):
                        self.components.remove(c)
            return

        pt_future_start = parse_temporal(future_comp["dtstart"], "dtstart")
        delta = (
            pt_future_start.value - pt_split.value
            if pt_future_start.is_date == pt_split.is_date
            else datetime.timedelta(0)
        )
        future_rids = {
            rid
            for rid, _, _ in expand_component_candidates(
                future_comp, include_exdates=True
            )
        }
        for c in list(uid_comps):
            if c is not target_seg and c.get("recurrence_id") is not None:
                pt_c_rid = align_rid_to_master(c["recurrence_id"], pt_seg_start)
                if pt_c_rid.dt_utc_or_naive < cutoff_cmp:
                    continue
                self._shift_override_in_place(c, delta, pt_seg_start, pt_future_start)
                if c["recurrence_id"] in future_rids:
                    c["uid"] = future_comp["uid"]
                else:
                    self.components.remove(c)
