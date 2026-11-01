"""Clean-room Series Split (`Range=THIS_AND_FUTURE`) Mixin for ReferenceStore.

Implements `THIS_AND_FUTURE` series splitting, `COUNT` recalculation, `RDATE`/`EXDATE`
partitioning, multi-split chains, `NEW_UID` `NEXT`/`FIRST` linking, and override
migration/discard policies (R-L3-001, R-L3-004, R-L3-005, R-L3-007, R-L3-008, R-L5-002).
"""

from __future__ import annotations

import copy
import datetime
from typing import Any

from .oracle_base import OracleBase
from .oracle_canonical import (
    CORE_COMPONENT_KEYS,
    apply_patch_fields_in_place,
    canonical_temporal_str,
    partition_future_dates,
)
from .oracle_policy import (
    SingleEditExdateMode,
    SplitFutureOverrideMode,
    StoreError,
    ThisAndFutureSplitMode,
)
from .oracle_temporal import (
    ParsedTemporal,
    add_temporal_duration,
    align_rid_to_master,
    compute_wall_clock_delta,
    expand_component_candidates,
    format_canonical_rid,
    format_temporal_like,
    parse_temporal,
    replace_rrule_count,
    shift_wall_clock,
)


class OracleSplitMixin(OracleBase):
    """Mixin implementing Range=THIS_AND_FUTURE edit operations for ReferenceStore."""

    def _collect_superseded_downstream(
        self,
        uid_comps: list[dict[str, Any]],
        target_seg: dict[str, Any],
        pt_seg_start: ParsedTemporal,
        cutoff_cmp: datetime.datetime,
    ) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], ParsedTemporal]]]:
        """Collect superseded downstream recurring segments and standalone overrides >= cutoff_cmp."""
        superseded_segs: list[dict[str, Any]] = []
        target_overrides: list[tuple[dict[str, Any], ParsedTemporal]] = []

        for c in uid_comps:
            if c is target_seg or c.get("recurrence_id") is None:
                continue
            if (
                align_rid_to_master(c["recurrence_id"], pt_seg_start).dt_utc_or_naive
                < cutoff_cmp
            ):
                continue
            if c.get("rrule") or c.get("rdate"):
                superseded_segs.append(c)
            else:
                target_overrides.append((c, pt_seg_start))

        next_uids = set(self._collect_next_linked_uids(target_seg))
        for c in self.components if next_uids else ():
            if c.get("type") == "VTIMEZONE" or c.get("uid") not in next_uids:
                continue
            if c.get("rrule") or c.get("rdate") or c.get("recurrence_id") is None:
                superseded_segs.append(c)
            else:
                owner = next(
                    (
                        s
                        for s in self.components
                        if s.get("uid") == c.get("uid")
                        and s.get("recurrence_id") is None
                        and s.get("dtstart")
                    ),
                    c,
                )
                target_overrides.append(
                    (c, parse_temporal(owner["dtstart"], "dtstart"))
                )

        superseded_segs.sort(
            key=lambda s: parse_temporal(s["dtstart"], "dtstart").dt_utc_or_naive
        )
        return superseded_segs, target_overrides

    @staticmethod
    def _recover_tail_rrule(
        target_seg: dict[str, Any],
        superseded_segs: list[dict[str, Any]],
    ) -> str | None:
        """Recover the pre-split tail bound when re-splitting earlier than a downstream split."""
        base_rrule = target_seg.get("rrule")
        if not base_rrule or "UNTIL=" not in base_rrule or not superseded_segs:
            return base_rrule
        last_rrule = superseded_segs[-1].get("rrule")
        if not last_rrule:
            return base_rrule
        last_parts = dict(p.split("=", 1) for p in last_rrule.split(";") if "=" in p)
        base_parts = [
            p
            for p in base_rrule.split(";")
            if p and not p.startswith(("COUNT=", "UNTIL="))
        ]
        if "COUNT" not in last_parts and "UNTIL" not in last_parts:
            return ";".join(base_parts)
        if "UNTIL" in last_parts:
            return ";".join([*base_parts, f"UNTIL={last_parts['UNTIL']}"])
        seg_count = sum(
            1
            for seg in [target_seg, *superseded_segs[:-1]]
            for _ in expand_component_candidates(
                {**seg, "rdate": []}, include_exdates=True
            )
        )
        return ";".join([*base_parts, f"COUNT={seg_count + int(last_parts['COUNT'])}"])

    def _resolve_future_rrule(
        self,
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        split_cmp: datetime.datetime,
        superseded_segs: list[dict[str, Any]],
        pt_seg_start: ParsedTemporal,
        pt_future_start: ParsedTemporal,
    ) -> str | None:
        """Resolve RRULE for the forked future segment (respecting explicit patch COUNT)."""
        if "rrule" in patch:
            return patch["rrule"]
        future_rrule = self._recover_tail_rrule(target_seg, superseded_segs)
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

    def _allocate_split_uid_and_links(
        self,
        target_seg: dict[str, Any],
        canon_split_rid: str,
        patch: dict[str, Any],
    ) -> tuple[str, str | None, list[dict[str, str]]]:
        """Compute (future_uid, future_rid, future_related_to) and update target_seg NEXT link."""
        inherited_rels = [
            {"uid": str(r["uid"]), "reltype": str(r.get("reltype") or "PARENT")}
            for r in copy.deepcopy(
                patch.get("related_to", target_seg.get("related_to") or [])
            )
            if str(r.get("reltype") or "PARENT").upper() not in ("NEXT", "FIRST")
        ]
        if self.policy.this_and_future_split_mode == ThisAndFutureSplitMode.SHARED_UID:
            return target_seg["uid"], canon_split_rid, inherited_rels

        base_uid = f"{target_seg['uid']}-split-{canon_split_rid}"
        existing_uids = {
            c.get("uid") for c in self.components if c.get("type") != "VTIMEZONE"
        }
        future_uid, suffix = base_uid, 2
        while future_uid in existing_uids:
            future_uid = f"{base_uid}-{suffix}"
            suffix += 1

        first_uid = next(
            (
                str(r["uid"])
                for r in (target_seg.get("related_to") or [])
                if str(r.get("reltype") or "").upper() == "FIRST" and r.get("uid")
            ),
            target_seg["uid"],
        )
        target_seg["related_to"] = [
            r
            for r in (target_seg.get("related_to") or [])
            if str(r.get("reltype") or "").upper() != "NEXT"
        ] + [{"uid": future_uid, "reltype": "NEXT"}]
        return (
            future_uid,
            None,
            [*inherited_rels, {"uid": first_uid, "reltype": "FIRST"}],
        )

    def _build_forked_future_comp(
        self,
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        pt_split: ParsedTemporal,
        pt_seg_start: ParsedTemporal,
        split_cmp: datetime.datetime,
        canon_split_rid: str,
        superseded_segs: list[dict[str, Any]],
        eff_now: str,
    ) -> dict[str, Any]:
        """Build the canonical forked future segment for a THIS_AND_FUTURE edit (R-L3-001..R-L3-005)."""
        orig_dur = self._compute_duration(target_seg)
        default_dtstart = format_temporal_like(pt_split.value, pt_seg_start)
        future_dtstart = canonical_temporal_str(
            patch.get("dtstart", default_dtstart), "dtstart"
        )
        assert future_dtstart is not None
        pt_future_start = parse_temporal(future_dtstart, "dtstart")
        is_todo = target_seg["type"] == "VTODO"
        end_key = "due" if is_todo else "dtend"
        if end_key in patch:
            future_end = canonical_temporal_str(patch[end_key], end_key)
        elif orig_dur is not None:
            future_end = format_temporal_like(
                add_temporal_duration(
                    pt_future_start.value, orig_dur, min_days=(0 if is_todo else 1)
                ),
                pt_future_start,
            )
        else:
            future_end = None

        future_rrule = self._resolve_future_rrule(
            target_seg, patch, split_cmp, superseded_segs, pt_seg_start, pt_future_start
        )
        future_uid, future_rid, future_rels = self._allocate_split_uid_and_links(
            target_seg, canon_split_rid, patch
        )
        old_seq = target_seg.get("sequence") or 0
        all_segs = [target_seg, *superseded_segs]
        future_comp: dict[str, Any] = {
            "type": target_seg["type"],
            "uid": future_uid,
            "recurrence_id": future_rid,
            "summary": patch.get("summary", target_seg.get("summary")),
            "dtstart": future_dtstart,
            end_key: future_end,
            "rrule": future_rrule,
            "rdate": partition_future_dates(all_segs, patch, "rdate", split_cmp),
            "exdate": partition_future_dates(all_segs, patch, "exdate", split_cmp),
            "dtstamp": eff_now,
            "created": eff_now,
            "sequence": old_seq + 1 if old_seq else 1,
            "last_modified": eff_now,
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
        future_comp["related_to"] = future_rels
        for src_d in (target_seg, patch):
            for k, v in src_d.items():
                if k not in CORE_COMPONENT_KEYS:
                    future_comp[k] = copy.deepcopy(v)
        return future_comp

    def _migrate_split_overrides(
        self,
        future_comp: dict[str, Any],
        target_overrides: list[tuple[dict[str, Any], ParsedTemporal]],
        patch: dict[str, Any],
        pt_split: ParsedTemporal,
    ) -> None:
        """Migrate standalone overrides >= split onto future_comp (MIGRATE_TO_FUTURE_SERIES)."""
        pt_future_start = parse_temporal(future_comp["dtstart"], "dtstart")
        wall_delta = (
            compute_wall_clock_delta(pt_split, pt_future_start)
            if ("rrule" not in patch and pt_future_start.is_date == pt_split.is_date)
            else datetime.timedelta(0)
        )
        if wall_delta and "exdate" not in patch and future_comp.get("exdate"):
            future_comp["exdate"] = [
                format_temporal_like(
                    shift_wall_clock(parse_temporal(ex, "exdate").value, wall_delta),
                    pt_future_start,
                )
                for ex in future_comp["exdate"]
                if parse_temporal(ex, "exdate").is_date == pt_future_start.is_date
            ]
        future_rids = (
            {
                rid
                for rid, _, _ in expand_component_candidates(
                    future_comp, include_exdates=True
                )
            }
            if (future_comp.get("rrule") or future_comp.get("rdate"))
            else set()
        )
        for ov, pt_owner in target_overrides:
            if pt_owner.is_date != pt_future_start.is_date:
                if ov in self.components:
                    self.components.remove(ov)
                continue
            if wall_delta:
                self._shift_override_in_place(ov, wall_delta, pt_owner, pt_future_start)
            else:
                ov["recurrence_id"] = format_canonical_rid(
                    align_rid_to_master(ov["recurrence_id"], pt_future_start)
                )
            if ov["recurrence_id"] not in future_rids:
                if ov in self.components:
                    self.components.remove(ov)
                continue
            ov["uid"] = future_comp["uid"]
            self._validate_component_state(ov)
            self._register_comp_timezones(ov)
            if (
                self.policy.single_edit_exdate_mode
                == SingleEditExdateMode.LEGACY_DUAL_EXDATE
                and "exdate" not in patch
            ):
                pt_ov_rid = align_rid_to_master(ov["recurrence_id"], pt_future_start)
                cur_ex = {
                    format_canonical_rid(align_rid_to_master(x, pt_future_start))
                    for x in (future_comp.get("exdate") or [])
                }
                if ov["recurrence_id"] not in cur_ex:
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
        """Discard or migrate standalone overrides >= cutoff_cmp and reconcile future_comp exdates."""
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
            self._migrate_split_overrides(
                future_comp, target_overrides, patch, pt_split
            )
            return
        for ov, _ in target_overrides:
            if ov in self.components:
                self.components.remove(ov)
        future_comp["exdate"] = self._filter_valid_exdates(future_comp)

    def _edit_segment_start_in_place(
        self,
        target_seg: dict[str, Any],
        superseded_segs: list[dict[str, Any]],
        target_overrides: list[tuple[dict[str, Any], ParsedTemporal]],
        patch: dict[str, Any],
        pt_seg_start: ParsedTemporal,
        pt_split: ParsedTemporal,
        eff_now: str,
    ) -> None:
        """Apply a THIS_AND_FUTURE edit targeting the start of an existing split segment."""
        for seg in superseded_segs:
            if seg in self.components:
                self.components.remove(seg)
        orig_dur = self._compute_duration(target_seg)
        old_s, old_c = target_seg.get("status"), target_seg.get("completed")
        if "rrule" not in patch and superseded_segs:
            target_seg["rrule"] = self._recover_tail_rrule(target_seg, superseded_segs)
        apply_patch_fields_in_place(target_seg, patch)
        seg_rrule = target_seg.get("rrule")
        if (
            "dtstart" in patch
            and "rrule" not in patch
            and isinstance(seg_rrule, str)
            and "UNTIL=" in seg_rrule
            and target_seg.get("dtstart")
        ):
            self._align_rrule_until_on_dtstart_change(
                target_seg,
                pt_seg_start,
                parse_temporal(target_seg["dtstart"], "dtstart"),
            )
        self._shift_comp_end_or_due(target_seg, patch, orig_dur)
        self._apply_in_place_edit_metadata(target_seg, eff_now)
        self._update_todo_completed(target_seg, patch, old_s, old_c, eff_now)
        self._apply_split_override_policy(target_seg, target_overrides, patch, pt_split)
        self._validate_component_state(target_seg)
        self._register_comp_timezones(target_seg)

    def _edit_this_and_future(
        self,
        uid_comps: list[dict[str, Any]],
        recurring_segments: list[dict[str, Any]],
        patch: dict[str, Any],
        recurrence_id: str,
        eff_now: str,
    ) -> None:
        """Apply a THIS_AND_FUTURE edit after the master's first occurrence (R-L3-001..R-L3-008)."""
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
        canon_split_rid = format_canonical_rid(pt_split)
        is_seg_start = self._targets_seg_start(target_seg, recurrence_id)
        cutoff_cmp = self._segment_cutoff_cmp(
            target_seg, pt_seg_start, split_cmp, is_seg_start
        )
        superseded_segs, target_overrides = self._collect_superseded_downstream(
            uid_comps, target_seg, pt_seg_start, cutoff_cmp
        )

        if is_seg_start:
            self._edit_segment_start_in_place(
                target_seg,
                superseded_segs,
                target_overrides,
                patch,
                pt_seg_start,
                pt_split,
                eff_now,
            )
            return

        future_comp = self._build_forked_future_comp(
            target_seg,
            patch,
            pt_split,
            pt_seg_start,
            split_cmp,
            canon_split_rid,
            superseded_segs,
            eff_now,
        )
        for seg in superseded_segs:
            if seg in self.components:
                self.components.remove(seg)
        self._apply_split_override_policy(
            future_comp, target_overrides, patch, pt_split
        )
        self._truncate_segment_before(
            target_seg, pt_split, pt_seg_start, split_cmp, eff_now
        )
        self._validate_component_state(target_seg)
        self._validate_component_state(future_comp)
        self._ensure_unique_identity(future_comp["uid"], future_comp["recurrence_id"])
        self._register_comp_timezones(future_comp)
        self.components.insert(self.components.index(target_seg), future_comp)
