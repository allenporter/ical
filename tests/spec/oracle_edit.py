"""Clean-room Reference Store Edit Operations Mixin (L2, L3, L4, L5).

Implements whole-series edits of exactly one UID (R-L4-001, R-L4-002, R-L4-003, R-L4-004,
R-L4-005, R-L4-006, R-L4-007)
and single-instance overrides (`Range=NONE`, R-L2-003..R-L2-008), inheriting `THIS_AND_FUTURE`
split operations from `OracleSplitMixin` (R-L3-001..R-L3-008).
"""

from __future__ import annotations

import copy
import datetime
from typing import Any

from .oracle_canonical import (
    CORE_COMPONENT_KEYS,
    apply_patch_fields_in_place,
    canonical_temporal_str,
)
from .oracle_policy import (
    SeriesEditOverrideMode,
    SingleEditExdateMode,
    StoreError,
)
from .oracle_split import OracleSplitMixin
from .oracle_temporal import (
    ParsedTemporal,
    add_temporal_duration,
    align_rid_to_master,
    expand_component_candidates,
    format_canonical_rid,
    format_temporal_like,
    parse_temporal,
    shift_wall_clock,
)

_SCHEDULE_KEYS = frozenset(
    {
        "dtstart",
        "dtend",
        "due",
        "rrule",
        "rdate",
        "exdate",
        "recurrence_id",
        "dtstamp",
        "uid",
        "sequence",
        "created",
        "last_modified",
    }
)


class OracleEditMixin(OracleSplitMixin):
    """Mixin providing whole-series and single-instance edit handlers for ReferenceStore."""

    def _propagate_non_schedule_to_comp(
        self,
        comp: dict[str, Any],
        patch: dict[str, Any],
        non_schedule_keys: set[str],
        eff_now: str,
    ) -> None:
        """Apply non-schedule patch fields to a surviving segment or override and bump revision metadata."""
        if not non_schedule_keys:
            return
        old_s, old_c = comp.get("status"), comp.get("completed")
        sub_patch = {k: patch[k] for k in non_schedule_keys}
        apply_patch_fields_in_place(comp, sub_patch)
        self._update_todo_completed(comp, sub_patch, old_s, old_c, eff_now)
        self._apply_in_place_edit_metadata(comp, eff_now)
        self._validate_component_state(comp)
        self._register_comp_timezones(comp)

    def _propagate_whole_series_patch(
        self,
        master_comp: dict[str, Any],
        standalone_overrides: list[dict[str, Any]],
        patch: dict[str, Any],
        eff_now: str,
    ) -> None:
        """Prune orphaned overrides and propagate metadata patches (R-L4-003, R-L4-005, R-L4-008).

        Only this UID's overrides are touched: other segments of a split chain are
        separate series addressed by their own UIDs (R-L4-001).
        """
        non_schedule_keys = set(patch) - _SCHEDULE_KEYS
        propagate = (
            self.policy.series_edit_override_mode
            == SeriesEditOverrideMode.PROPAGATE_PATCH
        )
        pt_master = parse_temporal(master_comp["dtstart"], "dtstart")
        master_rids = {
            rid
            for rid, _, _ in expand_component_candidates(
                master_comp, include_exdates=True
            )
        }
        for ov in list(standalone_overrides):
            pt_ov_rid = parse_temporal(ov["recurrence_id"], "recurrence_id")
            is_valid = (
                pt_ov_rid.is_date == pt_master.is_date
                and format_canonical_rid(
                    align_rid_to_master(ov["recurrence_id"], pt_master)
                )
                in master_rids
            )
            if not is_valid:
                self.components.remove(ov)
            elif propagate:
                self._propagate_non_schedule_to_comp(
                    ov, patch, non_schedule_keys, eff_now
                )

    def _shift_overrides_with_series(
        self,
        standalone_overrides: list[dict[str, Any]],
        wall_delta: datetime.timedelta,
        pt_old_start: ParsedTemporal,
        pt_new_start: ParsedTemporal,
        eff_now: str,
    ) -> None:
        """SHIFT_WITH_SERIES: re-key overrides by the series shift as new revisions (R-L4-009).

        A shifted override is a revision at its new (UID, RECURRENCE-ID) key, so its
        SEQUENCE exceeds any SEQUENCE previously held at that key (I-T-005) and its
        DTSTAMP/LAST-MODIFIED are updated (I-T-006).
        """
        prior_seq = {
            ov["recurrence_id"]: ov.get("sequence") or 0 for ov in standalone_overrides
        }
        for ov in standalone_overrides:
            own_seq = ov.get("sequence") or 0
            self._shift_override_in_place(ov, wall_delta, pt_old_start, pt_new_start)
            ov["sequence"] = max(own_seq, prior_seq.get(ov["recurrence_id"], 0)) + 1
            ov["dtstamp"] = eff_now
            ov["last_modified"] = eff_now

    def _apply_master_dtstart_change(
        self,
        master_comp: dict[str, Any],
        standalone_overrides: list[dict[str, Any]],
        patch: dict[str, Any],
        pt_old_start: ParsedTemporal | None,
        orig_dur: datetime.timedelta | None,
        normalized_from_first_instance: bool,
        eff_now: str,
    ) -> None:
        """Update master exdate, rdate, rrule.until, dtend/due, and shifted overrides when dtstart changes."""
        pt_new_start = parse_temporal(master_comp["dtstart"], "dtstart")
        if pt_old_start is not None and pt_old_start.is_date != pt_new_start.is_date:
            if "exdate" not in patch:
                master_comp["exdate"] = []
            if "rdate" not in patch:
                master_comp["rdate"] = []
        wall_delta = self._should_shift_series_exceptions(
            patch, pt_old_start, pt_new_start, normalized_from_first_instance
        )
        if wall_delta and pt_old_start is not None:
            for list_k in ("exdate", "rdate"):
                if list_k not in patch and master_comp.get(list_k):
                    master_comp[list_k] = [
                        format_temporal_like(
                            shift_wall_clock(
                                parse_temporal(val, list_k).value, wall_delta
                            ),
                            pt_new_start,
                        )
                        for val in master_comp[list_k]
                    ]
            self._shift_overrides_with_series(
                standalone_overrides, wall_delta, pt_old_start, pt_new_start, eff_now
            )
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
        master_comp: dict[str, Any] | None,
        standalone_overrides: list[dict[str, Any]],
        patch: dict[str, Any],
        normalized_from_first_instance: bool,
        eff_now: str,
    ) -> None:
        """Apply a whole-series edit of exactly one UID (R-L3-002, R-L4-001..R-L4-007)."""
        if master_comp is None:
            raise StoreError(
                f"No master component found for whole-series edit of uid={uid!r}"
            )
        orig_dur = self._compute_duration(master_comp)
        old_s, old_c = master_comp.get("status"), master_comp.get("completed")
        pt_old_start = (
            parse_temporal(master_comp["dtstart"], "dtstart")
            if master_comp.get("dtstart")
            else None
        )
        apply_patch_fields_in_place(master_comp, patch)
        if "dtstart" in patch and master_comp.get("dtstart"):
            self._apply_master_dtstart_change(
                master_comp,
                standalone_overrides,
                patch,
                pt_old_start,
                orig_dur,
                normalized_from_first_instance,
                eff_now,
            )
        self._apply_in_place_edit_metadata(master_comp, eff_now)
        self._update_todo_completed(master_comp, patch, old_s, old_c, eff_now)

        if not master_comp.get("rrule") and not master_comp.get("rdate"):
            master_comp["exdate"] = []
            for ov in standalone_overrides:
                if ov in self.components:
                    self.components.remove(ov)
        elif normalized_from_first_instance and pt_old_start is not None:
            self._apply_split_override_policy(
                master_comp,
                [(ov, pt_old_start) for ov in standalone_overrides],
                patch,
                pt_old_start,
            )
        else:
            master_comp["exdate"] = self._filter_valid_exdates(master_comp)
            self._propagate_whole_series_patch(
                master_comp, standalone_overrides, patch, eff_now
            )
        self._validate_component_state(master_comp)
        self._register_comp_timezones(master_comp)

    def _build_forked_override_comp(
        self,
        target_seg: dict[str, Any],
        patch: dict[str, Any],
        canon_rid: str,
        default_dtstart: str,
        eff_now: str,
    ) -> dict[str, Any]:
        """Build a complete canonical single-instance override component (R-L2-003, R-L2-004)."""
        orig_dur = self._compute_duration(target_seg)
        new_dtstart = canonical_temporal_str(
            patch.get("dtstart", default_dtstart), "dtstart"
        )
        assert new_dtstart is not None
        pt_new_start = parse_temporal(new_dtstart, "dtstart")
        is_todo = target_seg["type"] == "VTODO"
        end_key = "due" if is_todo else "dtend"
        if end_key in patch:
            new_end = canonical_temporal_str(patch[end_key], end_key)
        elif orig_dur is not None:
            new_end = format_temporal_like(
                add_temporal_duration(
                    pt_new_start.value, orig_dur, min_days=(0 if is_todo else 1)
                ),
                pt_new_start,
            )
        else:
            new_end = None

        old_seq = target_seg.get("sequence") or 0
        override_comp: dict[str, Any] = {
            "type": target_seg["type"],
            "uid": target_seg["uid"],
            "recurrence_id": canon_rid,
            "summary": patch.get("summary", target_seg.get("summary")),
            "dtstart": new_dtstart,
            end_key: new_end,
            "rrule": None,
            "rdate": [],
            "exdate": [],
            "dtstamp": eff_now,
            "created": target_seg.get("created")
            or target_seg.get("dtstamp")
            or eff_now,
            "sequence": old_seq + 1 if old_seq else 1,
            "last_modified": eff_now,
        }
        if is_todo:
            override_comp["status"] = patch.get("status", target_seg.get("status"))
            override_comp["completed"] = canonical_temporal_str(
                patch.get("completed", target_seg.get("completed")), "completed"
            )
            self._update_todo_completed(
                override_comp,
                patch,
                target_seg.get("status"),
                target_seg.get("completed"),
                eff_now,
            )
        if "related_to" in patch:
            self._validate_related_to(patch)
            override_comp["related_to"] = [
                {"uid": str(r["uid"]), "reltype": str(r.get("reltype") or "PARENT")}
                for r in (patch.get("related_to") or [])
            ]
        else:
            override_comp["related_to"] = copy.deepcopy(
                target_seg.get("related_to") or []
            )
        for src_d in (target_seg, patch):
            for k, v in src_d.items():
                if k not in CORE_COMPONENT_KEYS:
                    override_comp[k] = copy.deepcopy(v)
        return override_comp

    def _update_existing_override_in_place(
        self, existing_ov: dict[str, Any], patch: dict[str, Any], eff_now: str
    ) -> None:
        """Update an already-forked standalone override in place (R-L2-006)."""
        orig_dur = self._compute_duration(existing_ov)
        old_s, old_c = existing_ov.get("status"), existing_ov.get("completed")
        clean_patch = {
            k: v
            for k, v in patch.items()
            if k not in ("rrule", "rdate", "exdate", "recurrence_id")
        }
        apply_patch_fields_in_place(existing_ov, clean_patch)
        existing_ov["rrule"] = None
        existing_ov["rdate"] = []
        existing_ov["exdate"] = []
        self._shift_comp_end_or_due(existing_ov, clean_patch, orig_dur)
        self._apply_in_place_edit_metadata(existing_ov, eff_now)
        self._update_todo_completed(existing_ov, clean_patch, old_s, old_c, eff_now)
        self._validate_component_state(existing_ov)
        self._register_comp_timezones(existing_ov)

    def _edit_single_instance(
        self,
        recurring_segments: list[dict[str, Any]],
        standalone_overrides: list[dict[str, Any]],
        patch: dict[str, Any],
        recurrence_id: str,
        eff_now: str,
    ) -> None:
        """Apply a single-instance edit (Range=NONE) (R-L1-005..R-L1-007, R-L2-003..R-L2-009)."""
        ref_seg = next((s for s in recurring_segments if s.get("dtstart")), None)
        ref_pt = (
            parse_temporal(ref_seg["dtstart"], "dtstart")
            if ref_seg is not None
            else None
        )
        existing_ov = self._find_override_for_rid(
            standalone_overrides, recurrence_id, ref_pt
        )
        target_seg = (
            None
            if existing_ov is not None
            else self._find_segment_for_rid(
                recurring_segments, recurrence_id, include_exdates=False
            )
        )
        if existing_ov is None and target_seg is None:
            raise StoreError(
                f"No active occurrence matching recurrence_id={recurrence_id!r} for single-instance edit"
            )
        if "rrule" in patch and patch["rrule"] is not None:
            if (
                existing_ov is not None
                or target_seg is None
                or patch["rrule"] != target_seg.get("rrule")
            ):
                raise StoreError(
                    "Cannot modify RRULE on a single-instance override (R-L2-007)"
                )
        if existing_ov is not None:
            self._update_existing_override_in_place(existing_ov, patch, eff_now)
            return

        assert target_seg is not None
        pt_seg_start = parse_temporal(target_seg["dtstart"], "dtstart")
        pt_rid = align_rid_to_master(recurrence_id, pt_seg_start)
        canon_rid = format_canonical_rid(pt_rid)
        default_dtstart = format_temporal_like(pt_rid.value, pt_seg_start)
        override_comp = self._build_forked_override_comp(
            target_seg, patch, canon_rid, default_dtstart, eff_now
        )
        self._validate_component_state(override_comp)
        self._ensure_unique_identity(
            override_comp["uid"], override_comp["recurrence_id"]
        )
        self._register_comp_timezones(override_comp)
        if (
            self.policy.single_edit_exdate_mode
            == SingleEditExdateMode.LEGACY_DUAL_EXDATE
        ):
            ex_list = list(target_seg.get("exdate") or [])
            ex_rids = {
                format_canonical_rid(align_rid_to_master(x, pt_seg_start))
                for x in ex_list
            }
            if canon_rid not in ex_rids:
                ex_list.append(default_dtstart)
            target_seg["exdate"] = ex_list
        self.components.insert(self.components.index(target_seg), override_comp)
