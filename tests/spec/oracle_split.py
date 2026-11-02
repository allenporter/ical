"""Clean-room Series Split (`Range=THIS_AND_FUTURE`) Mixin for ReferenceStore.

Implements the `THIS_AND_FUTURE` split prescribed by RFC 8984 Section 4.1.3 (R-L3-001):
the original recurring component is truncated before the split and a NEW recurring
component with a NEW UID and no RECURRENCE-ID represents the occurrences from the split
onward, linked by RELTYPE=NEXT (original -> new) and RELTYPE=FIRST (new -> first
component of the chain). Also implements `COUNT` recalculation (R-L3-004), end/due/duration
realignment (R-L3-005), override discard/migration (R-L3-006), `RDATE`/`EXDATE`
partitioning (R-L3-007), chain insertion on re-split (R-L3-008), and wall-clock shift (R-L3-010).
"""

from __future__ import annotations

import copy
import datetime
from typing import Any

from .oracle_base import OracleBase
from .oracle_canonical import (
    CORE_COMPONENT_KEYS,
    canonical_temporal_str,
)
from .oracle_duration import canonical_duration_str, coerce_duration_for_date
from .oracle_policy import (
    SingleEditExdateMode,
    SplitFutureOverrideMode,
    StoreError,
)
from .oracle_schedule import (
    adapted_rrule_for_anchor,
    dedup_temporals,
    partition_future_dates,
    shift_temporal_list_wall_clock,
)
from .oracle_temporal import (
    ParsedTemporal,
    _expand_rrule_occurrences,
    add_temporal_duration,
    align_rid_to_master,
    compute_wall_clock_delta,
    expand_component_candidates,
    format_canonical_rid,
    format_stored_rid,
    format_temporal_like,
    parse_temporal,
    temporal_class,
)


def _reltype(rel: dict[str, Any]) -> str:
    return str(rel.get("reltype") or "PARENT").upper()


class OracleSplitMixin(OracleBase):
    """Mixin implementing Range=THIS_AND_FUTURE edit operations for ReferenceStore."""

    @staticmethod
    def _collect_future_overrides(
        standalone_overrides: list[dict[str, Any]],
        pt_seg_start: ParsedTemporal,
        split_cmp: datetime.datetime,
    ) -> list[tuple[dict[str, Any], ParsedTemporal]]:
        """Overrides whose RECURRENCE-ID (not rescheduled DTSTART) is >= the split (R-L3-006)."""
        matched = [
            (align_rid_to_master(ov["recurrence_id"], pt_seg_start), ov)
            for ov in standalone_overrides
        ]
        matched.sort(
            key=lambda pair: (pair[0].dt_utc_or_naive, format_canonical_rid(pair[0]))
        )
        return [
            (ov, pt_seg_start)
            for pt_rid, ov in matched
            if pt_rid.dt_utc_or_naive >= split_cmp
        ]

    def _resolve_split_schedule(
        self,
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        pt_split: ParsedTemporal,
        pt_seg_start: ParsedTemporal,
        split_cmp: datetime.datetime,
    ) -> tuple[str, ParsedTemporal, str | None, list[str]]:
        """Resolve (future_dtstart, pt_future_start, future_rrule, extra_rdates)."""
        default_dtstart = format_temporal_like(pt_split.value, pt_seg_start)
        if "dtstart" in patch and patch["dtstart"] is None:
            raise StoreError("THIS_AND_FUTURE split requires non-null dtstart")
        raw_dtstart = patch.get("dtstart", default_dtstart)
        future_dtstart = canonical_temporal_str(raw_dtstart, "dtstart")
        assert future_dtstart is not None
        pt_future_start = parse_temporal(future_dtstart, "dtstart")

        if "rrule" in patch:
            r_val = patch["rrule"]
            if r_val is not None and (not isinstance(r_val, str) or not r_val):
                raise StoreError(f"Invalid rrule in patch: {r_val!r}")
            return future_dtstart, pt_future_start, r_val, []

        rrule_str = target_seg.get("rrule")
        if not rrule_str:
            return future_dtstart, pt_future_start, None, []

        rem_pts = [
            pt
            for _, pt, _ in expand_component_candidates(
                {**target_seg, "rdate": []}, include_exdates=True
            )
            if pt.dt_utc_or_naive >= split_cmp
        ]
        if not rem_pts:
            return future_dtstart, pt_future_start, None, []
        if "dtstart" in patch:
            cand_rrule = adapted_rrule_for_anchor(
                rrule_str, len(rem_pts), patch, pt_split, pt_seg_start, pt_future_start
            )
            return future_dtstart, pt_future_start, cand_rrule, []

        is_bounded = "COUNT=" in rrule_str.upper() or "UNTIL=" in rrule_str.upper()
        for idx, pt_cand in enumerate(rem_pts):
            cand_rrule = adapted_rrule_for_anchor(
                rrule_str, len(rem_pts) - idx, patch, pt_split, pt_seg_start, pt_cand
            )
            exp_utcs = sorted(
                p.dt_utc_or_naive
                for p in _expand_rrule_occurrences(cand_rrule, pt_cand).values()
            )
            target_utcs = [p.dt_utc_or_naive for p in rem_pts[idx:]]
            matches = (
                exp_utcs == target_utcs
                if is_bounded
                else exp_utcs[: len(target_utcs)] == target_utcs
            )
            if matches:
                if idx == 0 and pt_split.dt_utc_or_naive == pt_cand.dt_utc_or_naive:
                    return future_dtstart, pt_future_start, cand_rrule, []
                anchor_str = format_temporal_like(pt_cand.value, pt_seg_start)
                pt_anchor = parse_temporal(anchor_str, "dtstart")
                spill = [default_dtstart] + [
                    format_temporal_like(p.value, pt_seg_start) for p in rem_pts[:idx]
                ]
                return anchor_str, pt_anchor, cand_rrule, spill

        spill_all = [default_dtstart] + [
            format_temporal_like(p.value, pt_seg_start) for p in rem_pts
        ]
        return future_dtstart, pt_future_start, None, spill_all

    def _resolve_new_uid(
        self, target_seg: dict[str, Any], canon_split_rid: str, new_uid: str | None
    ) -> str:
        """UID of the new segment: the caller's `new_uid`, else a deterministic one (R-L3-001)."""
        existing = {
            c.get("uid") for c in self.components if c.get("type") != "VTIMEZONE"
        }
        if new_uid is not None:
            if not isinstance(new_uid, str) or not new_uid:
                raise StoreError(
                    f"Invalid new_uid {new_uid!r} for THIS_AND_FUTURE split"
                )
            if new_uid in existing:
                raise StoreError(f"new_uid {new_uid!r} already exists in the calendar")
            return new_uid
        base_uid = f"{target_seg['uid']}-split-{canon_split_rid}"
        future_uid, suffix = base_uid, 2
        while future_uid in existing:
            future_uid = f"{base_uid}-{suffix}"
            suffix += 1
        return future_uid

    @staticmethod
    def _link_split_segments(
        target_seg: dict[str, Any], patch: dict[str, Any], future_uid: str
    ) -> list[dict[str, str]]:
        """Point the original's NEXT at the new segment; return the new segment's links."""
        own = target_seg.get("related_to") or []
        inherited = [
            {"uid": str(r["uid"]), "reltype": str(r.get("reltype") or "PARENT")}
            for r in copy.deepcopy(patch.get("related_to", own))
            if _reltype(r) not in ("NEXT", "FIRST")
        ]
        old_next = [
            {"uid": str(r["uid"]), "reltype": "NEXT"}
            for r in own
            if _reltype(r) == "NEXT"
        ]
        first_uid = next(
            (str(r["uid"]) for r in own if _reltype(r) == "FIRST" and r.get("uid")),
            target_seg["uid"],
        )
        target_seg["related_to"] = [r for r in own if _reltype(r) != "NEXT"] + [
            {"uid": future_uid, "reltype": "NEXT"}
        ]
        return [*inherited, *old_next, {"uid": first_uid, "reltype": "FIRST"}]

    def _future_end_and_duration(
        self,
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        pt_future_start: ParsedTemporal,
    ) -> tuple[str | None, str | None]:
        """Resolve (dtend_or_due, duration) for a forked segment or override (R-L2-003, R-L3-005)."""
        is_todo = target_seg["type"] == "VTODO"
        end_key = "due" if is_todo else "dtend"
        other_end = "dtend" if is_todo else "due"
        if patch.get(other_end) is not None:
            raise StoreError(f"Cannot set {other_end} on {target_seg['type']}")
        if patch.get("duration") is not None and patch.get(end_key) is not None:
            raise StoreError(
                "Cannot specify both dtend/due and duration in patch (I-C-003)"
            )
        if end_key in patch and patch[end_key] is not None:
            return canonical_temporal_str(patch[end_key], end_key), None
        if "duration" in patch:
            return None, canonical_duration_str(patch["duration"], "duration")
        if end_key in patch:
            return None, None
        if target_seg.get("duration") is not None:
            return None, coerce_duration_for_date(
                target_seg["duration"], pt_future_start.is_date
            )
        orig_dur = self._compute_duration(target_seg)
        if target_seg.get(end_key) is not None and orig_dur is not None:
            return (
                format_temporal_like(
                    add_temporal_duration(pt_future_start.value, orig_dur, min_days=1),
                    pt_future_start,
                ),
                None,
            )
        return None, None

    def _build_forked_future_comp(
        self,
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        pt_split: ParsedTemporal,
        pt_seg_start: ParsedTemporal,
        future_uid: str,
        eff_now: str,
    ) -> dict[str, Any]:
        """Build the new recurring segment (new UID, no RECURRENCE-ID) (R-L3-001, R-L5-002)."""
        if "type" in patch and patch["type"] != target_seg["type"]:
            raise StoreError("Cannot change component type during THIS_AND_FUTURE edit")
        split_cmp = pt_split.dt_utc_or_naive
        future_dtstart, pt_future_start, future_rrule, extra_rdates = (
            self._resolve_split_schedule(
                target_seg, patch, pt_split, pt_seg_start, split_cmp
            )
        )
        end_val, dur_val = self._future_end_and_duration(
            target_seg, patch, pt_future_start
        )
        rdate_vals = partition_future_dates(
            [target_seg], patch, "rdate", split_cmp, pt_future_start
        )
        if extra_rdates and "rdate" not in patch:
            rdate_vals = dedup_temporals([*extra_rdates, *rdate_vals], pt_future_start)
        if not future_rrule and not rdate_vals:
            if "rrule" in patch or "rdate" in patch:
                raise StoreError(
                    "THIS_AND_FUTURE split segment must remain recurring (I-T-007)"
                )
            rdate_vals = [future_dtstart]

        is_todo = target_seg["type"] == "VTODO"
        future_comp: dict[str, Any] = {
            "type": target_seg["type"],
            "uid": future_uid,
            "recurrence_id": None,
            "summary": patch.get("summary", target_seg.get("summary")),
            "dtstart": future_dtstart,
            ("due" if is_todo else "dtend"): end_val,
            "duration": dur_val,
            "rrule": future_rrule,
            "rdate": rdate_vals,
            "exdate": partition_future_dates(
                [target_seg], patch, "exdate", split_cmp, pt_future_start
            ),
            "dtstamp": eff_now,
            "created": eff_now,
            "sequence": 0,
            "last_modified": None,
        }
        if is_todo:
            future_comp["status"] = patch.get("status", target_seg.get("status"))
            future_comp["completed"] = canonical_temporal_str(
                patch.get("completed", target_seg.get("completed")), "completed"
            )
            self._update_todo_completed(
                future_comp,
                patch,
                target_seg.get("status"),
                target_seg.get("completed"),
                eff_now,
            )
        future_comp["related_to"] = self._link_split_segments(
            target_seg, patch, future_uid
        )
        for src_d in (target_seg, patch):
            for k, v in src_d.items():
                if k not in CORE_COMPONENT_KEYS:
                    future_comp[k] = copy.deepcopy(v)
        return future_comp

    @staticmethod
    def _rekey_override(
        ov: dict[str, Any],
        pt_owner: ParsedTemporal,
        future_comp: dict[str, Any],
        future_rids: set[str],
    ) -> bool:
        """Re-key an override to the new segment, keeping its RECURRENCE-ID instant (R-L3-006)."""
        pt_future_start = parse_temporal(future_comp["dtstart"], "dtstart")
        if temporal_class(pt_owner) != temporal_class(pt_future_start):
            return False
        if ov.get("dtstart") and temporal_class(
            parse_temporal(ov["dtstart"], "dtstart")
        ) != temporal_class(pt_future_start):
            return False
        try:
            pt_inst = align_rid_to_master(ov["recurrence_id"], pt_owner)
            pt_aligned = align_rid_to_master(pt_inst.raw, pt_future_start)
            canon = format_canonical_rid(pt_aligned)
        except StoreError:
            return False
        if canon not in future_rids:
            return False
        ov["recurrence_id"] = format_stored_rid(pt_aligned)
        ov["uid"] = future_comp["uid"]
        return True

    def _migrate_split_overrides(
        self,
        future_comp: dict[str, Any],
        target_overrides: list[tuple[dict[str, Any], ParsedTemporal]],
        patch: dict[str, Any],
    ) -> None:
        """MIGRATE_TO_FUTURE_SERIES: keep overrides on active candidates of the new segment."""
        ordered_overrides = sorted(
            target_overrides,
            key=lambda item: (
                align_rid_to_master(item[0]["recurrence_id"], item[1]).dt_utc_or_naive,
                format_canonical_rid(
                    align_rid_to_master(item[0]["recurrence_id"], item[1])
                ),
            ),
        )
        pt_future_start = parse_temporal(future_comp["dtstart"], "dtstart")
        future_rids = {
            rid
            for rid, _, _ in expand_component_candidates(
                future_comp, include_exdates=False
            )
        }
        legacy_dual = (
            self.policy.single_edit_exdate_mode
            == SingleEditExdateMode.LEGACY_DUAL_EXDATE
            and "exdate" not in patch
        )
        for ov, pt_owner in ordered_overrides:
            if not self._rekey_override(ov, pt_owner, future_comp, future_rids):
                if ov in self.components:
                    self.components.remove(ov)
                continue
            self._validate_component_state(ov)
            self._register_comp_timezones(ov)
            cur_ex = {
                format_canonical_rid(align_rid_to_master(x, pt_future_start))
                for x in (future_comp.get("exdate") or [])
            }
            pt_ov_rid = align_rid_to_master(ov["recurrence_id"], pt_future_start)
            if legacy_dual and format_canonical_rid(pt_ov_rid) not in cur_ex:
                future_comp["exdate"].append(
                    format_temporal_like(pt_ov_rid.value, pt_future_start)
                )
        future_comp["exdate"] = self._filter_valid_exdates(future_comp)

    def _apply_split_override_policy(
        self,
        future_comp: dict[str, Any],
        target_overrides: list[tuple[dict[str, Any], ParsedTemporal]],
        patch: dict[str, Any],
        pt_split: ParsedTemporal,
        pt_seg_start: ParsedTemporal,
    ) -> None:
        """Discard or migrate overrides >= the split and realign EXDATE/RDATE (R-L3-006, R-L3-010)."""
        old_ov_rids = {
            format_canonical_rid(align_rid_to_master(ov["recurrence_id"], pt_owner))
            for ov, pt_owner in target_overrides
        }
        if "exdate" not in patch and old_ov_rids and future_comp.get("dtstart"):
            future_comp["exdate"] = [
                ex
                for ex in (future_comp.get("exdate") or [])
                if format_canonical_rid(
                    align_rid_to_master(ex, pt_seg_start)
                    if temporal_class(parse_temporal(ex, "exdate"))
                    == temporal_class(pt_seg_start)
                    else parse_temporal(ex, "exdate")
                )
                not in old_ov_rids
            ]
        if "dtstart" in patch and "rrule" not in patch and future_comp.get("dtstart"):
            pt_fs = parse_temporal(future_comp["dtstart"], "dtstart")
            if temporal_class(pt_split) == temporal_class(pt_fs):
                wall_delta = compute_wall_clock_delta(pt_split, pt_fs)
                if wall_delta:
                    for list_k in ("exdate", "rdate"):
                        if list_k not in patch and future_comp.get(list_k):
                            future_comp[list_k] = shift_temporal_list_wall_clock(
                                future_comp[list_k],
                                pt_seg_start,
                                pt_fs,
                                wall_delta,
                                list_k,
                            )
        if self.policy.split_future_override_mode != SplitFutureOverrideMode.DISCARD:
            self._migrate_split_overrides(future_comp, target_overrides, patch)
            return
        for ov, _ in target_overrides:
            if ov in self.components:
                self.components.remove(ov)
        future_comp["exdate"] = self._filter_valid_exdates(future_comp)

    def _edit_this_and_future(
        self,
        recurring_segments: list[dict[str, Any]],
        standalone_overrides: list[dict[str, Any]],
        patch: dict[str, Any],
        recurrence_id: str,
        eff_now: str,
        new_uid: str | None = None,
    ) -> None:
        """Split at a non-first instance: truncate the original, add a new-UID segment (R-L3-001..R-L3-010)."""
        target_seg = self._find_segment_for_rid(
            recurring_segments, recurrence_id, include_exdates=True
        )
        if target_seg is None:
            raise StoreError(
                f"No candidate occurrence matching recurrence_id={recurrence_id!r} for THIS_AND_FUTURE edit"
            )
        pt_seg_start = parse_temporal(target_seg["dtstart"], "dtstart")
        pt_split = align_rid_to_master(recurrence_id, pt_seg_start)
        split_cmp = pt_split.dt_utc_or_naive
        target_overrides = self._collect_future_overrides(
            standalone_overrides, pt_seg_start, split_cmp
        )
        future_obs = {id(ov) for ov, _ in target_overrides}
        has_prior_overrides = any(
            id(ov) not in future_obs for ov in standalone_overrides
        )
        future_uid = self._resolve_new_uid(
            target_seg, format_canonical_rid(pt_split), new_uid
        )
        future_comp = self._build_forked_future_comp(
            target_seg, patch, pt_split, pt_seg_start, future_uid, eff_now
        )
        self._apply_split_override_policy(
            future_comp, target_overrides, patch, pt_split, pt_seg_start
        )
        self._truncate_segment_before(
            target_seg,
            pt_split,
            pt_seg_start,
            split_cmp,
            eff_now,
            has_surviving_overrides=has_prior_overrides,
        )
        self._validate_component_state(target_seg)
        self._validate_component_state(future_comp)
        self._register_comp_timezones(future_comp)
        self.components.insert(self.components.index(target_seg), future_comp)
