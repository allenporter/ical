"""Clean-room Reference Store Edit Operations Mixin (L2, L3, L4, L5).

Implements whole-series edits (R-L4-002, R-L4-003, R-L4-004, R-L4-005, R-L4-006, R-L4-007),
single-instance overrides (`Range=NONE`, R-L2-003, R-L2-004, R-L2-005, R-L2-006, R-L2-007,
R-L2-008), and `THIS_AND_FUTURE` series splitting (R-L3-001, R-L3-002, R-L3-003, R-L3-004,
R-L3-005, R-L3-006, R-L3-007, R-L3-008) for `ReferenceStore`.
"""

from __future__ import annotations

import datetime
from typing import Any

from .oracle_base import OracleBase
from .oracle_temporal import (
    ParsedTemporal,
    SeriesEditOverrideMode,
    SingleEditExdateMode,
    StoreError,
    ThisAndFutureSplitMode,
    align_rid_to_master,
    expand_component_candidates,
    format_canonical_rid,
    format_temporal_like,
    parse_temporal,
    replace_rrule_count,
)


_SCHEDULE_KEYS = {
    "dtstart",
    "dtend",
    "due",
    "rrule",
    "rdate",
    "exdate",
    "recurrence_id",
    "dtstamp",
}


class OracleEditMixin(OracleBase):
    """Mixin providing edit handlers for ReferenceStore."""

    def _propagate_whole_series_patch(
        self,
        uid: str,
        master_comp: dict[str, Any],
        recurring_segments: list[dict[str, Any]],
        standalone_overrides: list[dict[str, Any]],
        patch: dict[str, Any],
        normalized_from_first_instance: bool,
        now: str | None,
    ) -> None:
        """Prune orphaned segments/overrides and propagate metadata patches (R-L4-003, R-L4-005)."""
        non_schedule_keys = set(patch) - _SCHEDULE_KEYS
        schedule_redefined = bool(
            normalized_from_first_instance
            or {"dtstart", "rrule", "rdate"} & set(patch.keys())
        )
        for seg in list(recurring_segments):
            if seg is master_comp:
                continue
            if schedule_redefined or not seg.get("recurrence_id"):
                self.components.remove(seg)
            elif (
                self.policy.series_edit_override_mode
                == SeriesEditOverrideMode.PROPAGATE_PATCH
            ):
                old_s, old_c = seg.get("status"), seg.get("completed")
                for k in non_schedule_keys:
                    seg[k] = patch[k]
                self._update_todo_completed(seg, patch, old_s, old_c, now)

        surviving_segments = [
            c
            for c in self.components
            if c.get("type") != "VTIMEZONE"
            and c.get("uid") == uid
            and (c.get("rrule") or c.get("rdate"))
        ]
        valid_rids = {
            rid
            for seg in surviving_segments
            for rid, _, _ in expand_component_candidates(seg, include_exdates=True)
        }
        pt_master_start = parse_temporal(master_comp["dtstart"], "dtstart")
        for ov in list(standalone_overrides):
            if normalized_from_first_instance or not surviving_segments:
                self.components.remove(ov)
                continue
            pt_ov_rid = parse_temporal(ov["recurrence_id"], "recurrence_id")
            if (
                pt_ov_rid.is_date != pt_master_start.is_date
                or format_canonical_rid(
                    align_rid_to_master(ov["recurrence_id"], pt_master_start)
                )
                not in valid_rids
            ):
                self.components.remove(ov)
                continue
            if (
                self.policy.series_edit_override_mode
                == SeriesEditOverrideMode.PROPAGATE_PATCH
            ):
                old_s, old_c = ov.get("status"), ov.get("completed")
                for k in non_schedule_keys:
                    ov[k] = patch[k]
                self._update_todo_completed(ov, patch, old_s, old_c, now)

    def _apply_master_dtstart_change(
        self,
        master_comp: dict[str, Any],
        standalone_overrides: list[dict[str, Any]],
        patch: dict[str, Any],
        pt_old_start: ParsedTemporal | None,
        orig_dur: datetime.timedelta | None,
        normalized_from_first_instance: bool,
    ) -> None:
        """Update master exdate, rdate, rrule.until, dtend/due, and shifted overrides when dtstart changes."""
        pt_new_start = parse_temporal(master_comp["dtstart"], "dtstart")
        if pt_old_start is not None and pt_old_start.is_date != pt_new_start.is_date:
            if "exdate" not in patch and "exdate" in master_comp:
                master_comp["exdate"] = []
            if "rdate" not in patch and "rdate" in master_comp:
                master_comp["rdate"] = []
        delta = self._should_shift_series_exceptions(
            patch, pt_old_start, pt_new_start, normalized_from_first_instance
        )
        if delta and pt_old_start is not None:
            if "exdate" not in patch and master_comp.get("exdate"):
                master_comp["exdate"] = [
                    format_temporal_like(
                        parse_temporal(ex, "exdate").value + delta, pt_new_start
                    )
                    for ex in master_comp["exdate"]
                ]
            for ov in standalone_overrides:
                self._shift_override_in_place(ov, delta, pt_old_start, pt_new_start)
        if (
            "rrule" not in patch
            and master_comp.get("rrule")
            and "UNTIL=" in master_comp["rrule"]
        ):
            self._align_rrule_until_on_dtstart_change(
                master_comp, pt_old_start, pt_new_start
            )
        self._shift_comp_end_or_due(master_comp, patch, orig_dur)

    def _edit_whole_series(
        self,
        uid: str,
        uid_comps: list[dict[str, Any]],
        master_comp: dict[str, Any] | None,
        recurring_segments: list[dict[str, Any]],
        standalone_overrides: list[dict[str, Any]],
        patch: dict[str, Any],
        normalized_from_first_instance: bool,
        now: str | None,
    ) -> None:
        """Apply a whole-series edit (recurrence_id is None) (R-L1-007, R-L3-002, R-L4-002..R-L4-007)."""
        if master_comp is None:
            return
        orig_dur = self._compute_duration(master_comp)
        old_s, old_c = master_comp.get("status"), master_comp.get("completed")
        pt_old_start = (
            parse_temporal(master_comp["dtstart"], "dtstart")
            if master_comp.get("dtstart")
            else None
        )
        for k, v in patch.items():
            if k != "dtstamp":
                master_comp[k] = v

        if "dtstart" in patch and master_comp.get("dtstart"):
            self._apply_master_dtstart_change(
                master_comp,
                standalone_overrides,
                patch,
                pt_old_start,
                orig_dur,
                normalized_from_first_instance,
            )
        if normalized_from_first_instance and "recurrence_id" not in master_comp:
            self._insert_key_after(master_comp, "uid", "recurrence_id", None)
        self._update_edit_metadata(master_comp, patch, now)
        self._update_todo_completed(master_comp, patch, old_s, old_c, now)
        if not master_comp.get("rrule") and not master_comp.get("rdate"):
            if "exdate" in master_comp:
                master_comp["exdate"] = []
            for ov in list(uid_comps):
                if ov is not master_comp:
                    self.components.remove(ov)
            return
        if "exdate" in master_comp:
            if normalized_from_first_instance and "exdate" not in patch:
                purged_rids = {
                    format_canonical_rid(
                        parse_temporal(c["recurrence_id"], "recurrence_id")
                    )
                    for c in uid_comps
                    if c is not master_comp and c.get("recurrence_id") is not None
                }
                master_comp["exdate"] = [
                    ex
                    for ex in (master_comp.get("exdate") or [])
                    if format_canonical_rid(parse_temporal(ex, "exdate"))
                    not in purged_rids
                ]
            master_comp["exdate"] = self._filter_valid_exdates(master_comp)
        self._propagate_whole_series_patch(
            uid,
            master_comp,
            recurring_segments,
            standalone_overrides,
            patch,
            normalized_from_first_instance,
            now,
        )

    def _build_forked_override_comp(
        self,
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        canon_rid: str,
        default_dtstart: str,
        now: str | None,
    ) -> dict[str, Any]:
        """Build a new single-instance override component from target_seg (R-L2-003, R-L2-004)."""
        orig_dur = self._compute_duration(target_seg)
        new_dtstart = patch.get("dtstart", default_dtstart)
        pt_new_start = parse_temporal(new_dtstart, "dtstart")
        end_key = "due" if "due" in target_seg else "dtend"
        new_end: str | None = patch.get(end_key)
        if new_end is None and orig_dur is not None:
            new_end = format_temporal_like(pt_new_start.value + orig_dur, pt_new_start)

        override_comp: dict[str, Any] = {}
        if "type" in target_seg:
            override_comp["type"] = target_seg["type"]
        override_comp["uid"] = target_seg["uid"]
        rid_at_end = (
            "recurrence_id" in target_seg
            and list(target_seg.keys())[-1] == "recurrence_id"
        )
        if not rid_at_end:
            override_comp["recurrence_id"] = canon_rid
        self._copy_inherited_metadata(override_comp, target_seg, patch, now)
        override_comp["dtstart"] = new_dtstart
        if new_end is not None:
            override_comp[end_key] = new_end
        override_comp["rrule"] = None
        if "rdate" in target_seg:
            override_comp["rdate"] = []
        if (
            "rdate" in target_seg
            or "recurrence_id" in target_seg
            or "type" not in target_seg
        ) and "exdate" in target_seg:
            override_comp["exdate"] = []
        if rid_at_end:
            override_comp["recurrence_id"] = canon_rid
        if "sequence" in target_seg:
            old_seq = target_seg.get("sequence") or 0
            override_comp["sequence"] = old_seq + 1 if old_seq else 1
        return override_comp

    def _edit_single_instance(
        self,
        master_comp: dict[str, Any] | None,
        recurring_segments: list[dict[str, Any]],
        standalone_overrides: list[dict[str, Any]],
        patch: dict[str, Any],
        recurrence_id: str,
        now: str | None,
        append_override_at_end: bool,
    ) -> None:
        """Apply a single-instance edit (Range=NONE) (R-L1-005..R-L1-007, R-L2-003..R-L2-008)."""
        target_seg = (
            self._find_segment_for_rid(recurring_segments, recurrence_id) or master_comp
        )
        if target_seg is None:
            return
        pt_seg_start = parse_temporal(target_seg["dtstart"], "dtstart")
        pt_rid = align_rid_to_master(recurrence_id, pt_seg_start)
        canon_rid = format_canonical_rid(pt_rid)
        existing_ov = next(
            (
                ov
                for ov in standalone_overrides
                if format_canonical_rid(
                    align_rid_to_master(ov["recurrence_id"], pt_seg_start)
                )
                == canon_rid
            ),
            None,
        )
        if "rrule" in patch and patch["rrule"] is not None:
            if existing_ov is not None or patch["rrule"] != target_seg.get("rrule"):
                raise StoreError("Can't update single instance with rrule")
        if existing_ov is not None:
            orig_dur = self._compute_duration(existing_ov)
            old_s, old_c = existing_ov.get("status"), existing_ov.get("completed")
            for k, v in patch.items():
                if k not in ("rrule", "recurrence_id", "dtstamp"):
                    existing_ov[k] = v
            self._shift_comp_end_or_due(existing_ov, patch, orig_dur)
            self._update_edit_metadata(existing_ov, patch, now)
            self._update_todo_completed(existing_ov, patch, old_s, old_c, now)
            return
        default_dtstart = format_temporal_like(pt_rid.value, pt_seg_start)
        override_comp = self._build_forked_override_comp(
            target_seg, patch, canon_rid, default_dtstart, now
        )
        if "type" not in target_seg and "recurrence_id" not in target_seg:
            self._insert_key_after(target_seg, "uid", "recurrence_id", None)
        if "exdate" not in target_seg:
            target_seg["exdate"] = []
        if (
            self.policy.single_edit_exdate_mode
            == SingleEditExdateMode.LEGACY_DUAL_EXDATE
        ):
            ex_list = list(target_seg.get("exdate") or [])
            ex_rids = {
                format_canonical_rid(parse_temporal(x, "exdate")) for x in ex_list
            }
            if canon_rid not in ex_rids:
                ex_list.append(default_dtstart)
            target_seg["exdate"] = ex_list
        if append_override_at_end:
            self.components.append(override_comp)
        else:
            self.components.insert(self.components.index(target_seg), override_comp)

    def _populate_future_dates_and_seq(
        self,
        future_comp: dict[str, Any],
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        split_cmp: datetime.datetime,
        purged_override_rids: set[str],
    ) -> None:
        """Populate rdate, exdate, and sequence on a forked future segment."""
        if "rdate" in target_seg:
            future_comp["rdate"] = (
                list(patch["rdate"])
                if "rdate" in patch
                else [
                    rd
                    for rd in (target_seg.get("rdate") or [])
                    if parse_temporal(rd, "rdate").dt_utc_or_naive >= split_cmp
                ]
            )
        if "exdate" in target_seg:
            future_comp["exdate"] = [
                ex
                for ex in (target_seg.get("exdate") or [])
                if format_canonical_rid(parse_temporal(ex, "exdate"))
                not in purged_override_rids
            ]
            future_comp["exdate"] = self._filter_valid_exdates(future_comp)
        if "sequence" in target_seg:
            old_seq = target_seg.get("sequence") or 0
            future_comp["sequence"] = old_seq + 1 if old_seq else 1

    def _build_forked_future_comp(
        self,
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        pt_split: ParsedTemporal,
        pt_seg_start: ParsedTemporal,
        split_cmp: datetime.datetime,
        canon_split_rid: str,
        purged_override_rids: set[str],
        now: str | None,
    ) -> dict[str, Any]:
        """Build the forked future segment for a THIS_AND_FUTURE edit (R-L3-001, R-L3-004, R-L3-005)."""
        rrule_only_seg = {**target_seg, "rdate": []}
        prior_count = sum(
            1
            for _, pt_o, _ in expand_component_candidates(
                rrule_only_seg, include_exdates=True
            )
            if pt_o.dt_utc_or_naive < split_cmp
        )
        orig_dur = self._compute_duration(target_seg)
        default_dtstart = format_temporal_like(pt_split.value, pt_seg_start)
        future_dtstart = patch.get("dtstart", default_dtstart)
        pt_future_start = parse_temporal(future_dtstart, "dtstart")

        end_key = "due" if "due" in target_seg else "dtend"
        future_end: str | None = patch.get(end_key)
        if future_end is None and orig_dur is not None:
            future_end = format_temporal_like(
                pt_future_start.value + orig_dur, pt_future_start
            )
        future_rrule = patch.get("rrule", target_seg.get("rrule"))
        if future_rrule and "COUNT=" in future_rrule:
            parts = dict(p.split("=", 1) for p in future_rrule.split(";") if "=" in p)
            future_rrule = replace_rrule_count(
                future_rrule, max(1, int(parts["COUNT"]) - prior_count)
            )

        future_comp: dict[str, Any] = {}
        if "type" in target_seg:
            future_comp["type"] = target_seg["type"]
        if self.policy.this_and_future_split_mode == ThisAndFutureSplitMode.SHARED_UID:
            future_comp["uid"] = target_seg["uid"]
            future_comp["recurrence_id"] = canon_split_rid
        else:
            self._split_counter += 1
            future_comp["uid"] = f"{target_seg['uid']}-split-{canon_split_rid}"
            future_comp["recurrence_id"] = None

        self._copy_inherited_metadata(future_comp, target_seg, patch, now)
        future_comp["dtstart"] = future_dtstart
        if future_end is not None:
            future_comp[end_key] = future_end
        future_comp["rrule"] = future_rrule
        self._populate_future_dates_and_seq(
            future_comp, target_seg, patch, split_cmp, purged_override_rids
        )
        return future_comp

    def _edit_this_and_future(
        self,
        uid_comps: list[dict[str, Any]],
        recurring_segments: list[dict[str, Any]],
        patch: dict[str, Any],
        recurrence_id: str,
        now: str | None,
    ) -> None:
        """Apply a THIS_AND_FUTURE edit after the first instance (R-L3-001, R-L3-003..R-L3-008)."""
        target_seg = self._find_segment_for_rid(recurring_segments, recurrence_id)
        if target_seg is None:
            return
        pt_seg_start = parse_temporal(target_seg["dtstart"], "dtstart")
        pt_split = align_rid_to_master(recurrence_id, pt_seg_start)
        split_cmp = pt_split.dt_utc_or_naive
        canon_split_rid = format_canonical_rid(pt_split)
        is_seg_start = self._targets_seg_start(target_seg, recurrence_id)
        cutoff_cmp = self._segment_cutoff_cmp(
            target_seg, pt_seg_start, split_cmp, is_seg_start
        )

        purged_override_rids = {
            format_canonical_rid(align_rid_to_master(c["recurrence_id"], pt_seg_start))
            for c in uid_comps
            if c is not target_seg
            and c.get("recurrence_id") is not None
            and align_rid_to_master(c["recurrence_id"], pt_seg_start).dt_utc_or_naive
            >= cutoff_cmp
        }

        if is_seg_start:
            for c in list(uid_comps):
                if c is not target_seg and c.get("recurrence_id") is not None:
                    if (
                        align_rid_to_master(
                            c["recurrence_id"], pt_seg_start
                        ).dt_utc_or_naive
                        >= cutoff_cmp
                    ):
                        self.components.remove(c)
            orig_dur = self._compute_duration(target_seg)
            old_s, old_c = target_seg.get("status"), target_seg.get("completed")
            for k, v in patch.items():
                target_seg[k] = v
            self._shift_comp_end_or_due(target_seg, patch, orig_dur)
            if "exdate" in target_seg:
                if "exdate" not in patch and purged_override_rids:
                    target_seg["exdate"] = [
                        ex
                        for ex in (target_seg.get("exdate") or [])
                        if format_canonical_rid(parse_temporal(ex, "exdate"))
                        not in purged_override_rids
                    ]
                target_seg["exdate"] = self._filter_valid_exdates(target_seg)
            self._update_edit_metadata(target_seg, patch, now)
            self._update_todo_completed(target_seg, patch, old_s, old_c, now)
            return

        future_comp = self._build_forked_future_comp(
            target_seg,
            patch,
            pt_split,
            pt_seg_start,
            split_cmp,
            canon_split_rid,
            purged_override_rids,
            now,
        )
        self._handle_split_future_overrides(
            uid_comps, target_seg, future_comp, pt_seg_start, pt_split, cutoff_cmp
        )
        if "recurrence_id" not in target_seg:
            self._insert_key_after(target_seg, "uid", "recurrence_id", None)
        self._truncate_segment_before(target_seg, pt_split, pt_seg_start, split_cmp)
        self.components.insert(self.components.index(target_seg), future_comp)
