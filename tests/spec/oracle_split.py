"""Clean-room Series Split (`Range=THIS_AND_FUTURE`) Mixin for ReferenceStore.

Implements the `THIS_AND_FUTURE` split prescribed by RFC 8984 Section 4.1.3 (R-L3-001):
the original recurring component is truncated before the split and a NEW recurring
component with a NEW UID and no RECURRENCE-ID represents the occurrences from the split
onward, linked by RELTYPE=NEXT (original -> new) and RELTYPE=FIRST (new -> first
component of the chain). Also implements `COUNT` recalculation (R-L3-004), end/due
realignment (R-L3-005), override discard/migration (R-L3-006), `RDATE`/`EXDATE`
partitioning (R-L3-007), chain insertion on re-split (R-L3-008) and the new segment's
creation metadata (R-L5-001, R-L5-002).
"""

from __future__ import annotations

import copy
import datetime
from typing import Any

from .oracle_base import OracleBase
from .oracle_canonical import (
    CORE_COMPONENT_KEYS,
    canonical_temporal_str,
    partition_future_dates,
)
from .oracle_policy import (
    SingleEditExdateMode,
    SplitFutureOverrideMode,
    StoreError,
)
from .oracle_temporal import (
    ParsedTemporal,
    add_temporal_duration,
    align_rid_to_master,
    expand_component_candidates,
    format_canonical_rid,
    format_temporal_like,
    parse_temporal,
    replace_rrule_count,
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

    def _resolve_future_rrule(
        self,
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        split_cmp: datetime.datetime,
        pt_seg_start: ParsedTemporal,
        pt_future_start: ParsedTemporal,
    ) -> str | None:
        """RRULE of the new segment: explicit patch rule, else inherited with COUNT = N - k (R-L3-004)."""
        if "rrule" in patch:
            return patch["rrule"]
        future_rrule = target_seg.get("rrule")
        if future_rrule and "COUNT=" in future_rrule:
            prior_count = sum(
                1
                for _, pt_o, _ in expand_component_candidates(
                    {**target_seg, "rdate": []}, include_exdates=True
                )
                if pt_o.dt_utc_or_naive < split_cmp
            )
            parts = dict(p.split("=", 1) for p in future_rrule.split(";") if "=" in p)
            return replace_rrule_count(
                future_rrule, max(1, int(parts["COUNT"]) - prior_count)
            )
        if future_rrule and "UNTIL=" in future_rrule:
            tmp_c = {"rrule": future_rrule}
            self._align_rrule_until_on_dtstart_change(
                tmp_c, pt_seg_start, pt_future_start
            )
            return tmp_c["rrule"]
        return future_rrule

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
        """Point the original's NEXT at the new segment; return the new segment's links.

        The new segment inherits non-chain relations, takes over the original's NEXT
        (chain insertion, R-L3-008) and links FIRST to the chain head (R-L3-001).
        """
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

    def _future_end(
        self,
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        pt_future_start: ParsedTemporal,
    ) -> str | None:
        """DTEND/DUE of the new segment: explicit, else shifted by the original duration (R-L3-005)."""
        is_todo = target_seg["type"] == "VTODO"
        end_key = "due" if is_todo else "dtend"
        if end_key in patch:
            return canonical_temporal_str(patch[end_key], end_key)
        orig_dur = self._compute_duration(target_seg)
        if orig_dur is None:
            return None
        return format_temporal_like(
            add_temporal_duration(
                pt_future_start.value, orig_dur, min_days=(0 if is_todo else 1)
            ),
            pt_future_start,
        )

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
        split_cmp = pt_split.dt_utc_or_naive
        future_dtstart = canonical_temporal_str(
            patch.get("dtstart", format_temporal_like(pt_split.value, pt_seg_start)),
            "dtstart",
        )
        assert future_dtstart is not None
        pt_future_start = parse_temporal(future_dtstart, "dtstart")
        is_todo = target_seg["type"] == "VTODO"
        future_comp: dict[str, Any] = {
            "type": target_seg["type"],
            "uid": future_uid,
            "recurrence_id": None,
            "summary": patch.get("summary", target_seg.get("summary")),
            "dtstart": future_dtstart,
            ("due" if is_todo else "dtend"): self._future_end(
                target_seg, patch, pt_future_start
            ),
            "rrule": self._resolve_future_rrule(
                target_seg, patch, split_cmp, pt_seg_start, pt_future_start
            ),
            "rdate": partition_future_dates([target_seg], patch, "rdate", split_cmp),
            "exdate": partition_future_dates([target_seg], patch, "exdate", split_cmp),
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
        try:
            pt_inst = align_rid_to_master(ov["recurrence_id"], pt_owner)
            canon = format_canonical_rid(
                align_rid_to_master(pt_inst.raw, pt_future_start)
            )
        except StoreError:
            return False
        if canon not in future_rids:
            return False
        ov["recurrence_id"] = canon
        ov["uid"] = future_comp["uid"]
        return True

    def _migrate_split_overrides(
        self,
        future_comp: dict[str, Any],
        target_overrides: list[tuple[dict[str, Any], ParsedTemporal]],
        patch: dict[str, Any],
    ) -> None:
        """MIGRATE_TO_FUTURE_SERIES: keep overrides that are candidates of the new segment."""
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
                future_comp, include_exdates=True
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
            if legacy_dual and ov["recurrence_id"] not in cur_ex:
                pt_ov_rid = align_rid_to_master(ov["recurrence_id"], pt_future_start)
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
    ) -> None:
        """Discard or migrate overrides >= the split and reconcile the new segment's EXDATEs."""
        old_ov_rids = {
            format_canonical_rid(align_rid_to_master(ov["recurrence_id"], pt_owner))
            for ov, pt_owner in target_overrides
        }
        if "exdate" not in patch and old_ov_rids and future_comp.get("dtstart"):
            pt_fs = parse_temporal(future_comp["dtstart"], "dtstart")
            pt_ref = pt_split if pt_split.is_date == pt_fs.is_date else pt_fs
            future_comp["exdate"] = [
                ex
                for ex in (future_comp.get("exdate") or [])
                if format_canonical_rid(
                    align_rid_to_master(ex, pt_ref)
                    if parse_temporal(ex, "exdate").is_date == pt_ref.is_date
                    else parse_temporal(ex, "exdate")
                )
                not in old_ov_rids
            ]
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
        """Split at a non-first instance: truncate the original, add a new-UID segment (R-L3-001..R-L3-008)."""
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
        future_uid = self._resolve_new_uid(
            target_seg, format_canonical_rid(pt_split), new_uid
        )
        future_comp = self._build_forked_future_comp(
            target_seg, patch, pt_split, pt_seg_start, future_uid, eff_now
        )
        self._apply_split_override_policy(
            future_comp, target_overrides, patch, pt_split
        )
        self._truncate_segment_before(
            target_seg, pt_split, pt_seg_start, split_cmp, eff_now
        )
        self._validate_component_state(target_seg)
        self._validate_component_state(future_comp)
        self._register_comp_timezones(future_comp)
        self.components.insert(self.components.index(target_seg), future_comp)
