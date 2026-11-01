"""Clean-room Reference Store Oracle for iCalendar / CalDAV recurrence and editing semantics.

Implements a 100% standalone, RFC-grounded reference state machine and timeline expander
covering all 40 specification rules (R-L1-001 through R-L5-009) and all 5 explicit
configurable store policy modes (`PolicyConfig`) using ONLY the Python standard library
and `dateutil.rrule`.
"""

from __future__ import annotations

import copy
import datetime
from typing import Any

from .oracle_canonical import (
    CORE_COMPONENT_KEYS,
    DEFAULT_DTSTAMP,
    canonical_temporal_str,
)
from .oracle_edit import OracleEditMixin
from .oracle_policy import (
    ParentDeleteCascadeMode,
    PolicyConfig,
    SeriesEditOverrideMode,
    SeriesRescheduleExceptionMode,
    SingleEditExdateMode,
    SplitFutureOverrideMode,
    StoreError,
    is_policy_compatible,
    policy_from_modes,
)
from .oracle_temporal import (
    ParsedTemporal,
    add_temporal_duration,
    align_rid_to_master,
    compute_until_string,
    expand_component_candidates,
    format_canonical_rid,
    format_temporal_like,
    parse_temporal,
    replace_rrule_count,
    replace_rrule_until,
)

__all__ = [
    "ParentDeleteCascadeMode",
    "ParsedTemporal",
    "PolicyConfig",
    "ReferenceStore",
    "SeriesEditOverrideMode",
    "SeriesRescheduleExceptionMode",
    "SingleEditExdateMode",
    "SplitFutureOverrideMode",
    "StoreError",
    "align_rid_to_master",
    "compute_until_string",
    "expand_component_candidates",
    "format_canonical_rid",
    "format_temporal_like",
    "is_policy_compatible",
    "parse_temporal",
    "policy_from_modes",
    "replace_rrule_count",
    "replace_rrule_until",
]


class ReferenceStore(OracleEditMixin):
    """Clean-room Reference Store Oracle implementing R-L1-001 through R-L5-009."""

    def add(
        self,
        item: dict[str, Any],
        default_type: str | None = None,
        now: str = DEFAULT_DTSTAMP,
    ) -> dict[str, Any]:
        """Add a new VEVENT or VTODO component to the store (R-L5-001, R-L5-004..R-L5-009)."""
        saved = copy.deepcopy(self.components)
        try:
            out_comp = self._canonicalize_component(
                item, is_add=True, default_type=default_type, now=now
            )
            self._validate_component_state(out_comp)
            self._ensure_unique_identity(out_comp["uid"], out_comp["recurrence_id"])
            self._register_comp_timezones(out_comp)
            self.components.append(out_comp)
            return out_comp
        except Exception:
            self.components = saved
            raise

    def _delete_whole_uid_and_children(self, uid: str, eff_now: str) -> None:
        """Delete one UID plus PARENT-linked children per mode (R-L4-001, R-L5-007, R-L5-008, R-L5-009).

        NEXT/FIRST links are ordering relations, never PARENT: other segments of a split
        chain are neither deleted nor modified (links to the deleted UID may dangle).
        """
        delete_uids: set[str] = {uid}
        cascade_mode = self.policy.parent_delete_cascade_mode
        changed = cascade_mode == ParentDeleteCascadeMode.CASCADE_DELETE
        while changed:
            changed = False
            for comp in self.components:
                c_uid = comp.get("uid")
                if comp.get("type") == "VTIMEZONE" or not c_uid or c_uid in delete_uids:
                    continue
                if any(
                    rel.get("uid") in delete_uids and self._is_parent_relation(rel)
                    for rel in (comp.get("related_to") or ())
                ):
                    delete_uids.add(c_uid)
                    changed = True

        self.components = [
            c
            for c in self.components
            if c.get("type") == "VTIMEZONE" or c.get("uid") not in delete_uids
        ]
        if cascade_mode != ParentDeleteCascadeMode.DETACH_CHILDREN:
            return
        for comp in self.components:
            rels = comp.get("related_to") or []
            kept_rels = [
                r
                for r in rels
                if not (r.get("uid") in delete_uids and self._is_parent_relation(r))
            ]
            if len(kept_rels) != len(rels):
                comp["related_to"] = kept_rels
                self._bump_revision_metadata(comp, eff_now)

    def _delete_single_instance(
        self,
        recurring_segments: list[dict[str, Any]],
        standalone_overrides: list[dict[str, Any]],
        recurrence_id: str,
        eff_now: str,
    ) -> None:
        """Delete a single occurrence (Range=NONE) (R-L2-001, R-L2-002, R-L5-003)."""
        ref_seg = next((s for s in recurring_segments if s.get("dtstart")), None)
        ref_pt = (
            parse_temporal(ref_seg["dtstart"], "dtstart")
            if ref_seg is not None
            else None
        )
        existing_ov = self._find_override_for_rid(
            standalone_overrides, recurrence_id, ref_pt
        )
        target_seg = self._find_segment_for_rid(
            recurring_segments,
            recurrence_id,
            include_exdates=(existing_ov is not None),
        )
        if existing_ov is None and target_seg is None:
            raise StoreError(
                f"No active occurrence matching recurrence_id={recurrence_id!r} for single-instance delete"
            )
        if existing_ov is not None and existing_ov in self.components:
            self.components.remove(existing_ov)
        if target_seg is None:
            return

        pt_seg_start = parse_temporal(target_seg["dtstart"], "dtstart")
        pt_rid = align_rid_to_master(recurrence_id, pt_seg_start)
        canon_rid = format_canonical_rid(pt_rid)
        exdate_list = list(target_seg.get("exdate") or [])
        existing_ex_rids = {
            format_canonical_rid(align_rid_to_master(x, pt_seg_start))
            for x in exdate_list
        }
        if canon_rid not in existing_ex_rids:
            exdate_list.append(format_temporal_like(pt_rid.value, pt_seg_start))
            target_seg["exdate"] = exdate_list
            self._bump_revision_metadata(target_seg, eff_now)

    def _delete_this_and_future(
        self,
        recurring_segments: list[dict[str, Any]],
        standalone_overrides: list[dict[str, Any]],
        recurrence_id: str,
        eff_now: str,
    ) -> None:
        """Delete THIS_AND_FUTURE after the first occurrence: truncate this UID only (R-L3-003, R-L3-006..R-L3-008)."""
        target_seg = self._find_segment_for_rid(
            recurring_segments, recurrence_id, include_exdates=True
        )
        if target_seg is None:
            raise StoreError(
                f"No candidate occurrence matching recurrence_id={recurrence_id!r} for THIS_AND_FUTURE delete"
            )
        pt_seg_start = parse_temporal(target_seg["dtstart"], "dtstart")
        pt_split = align_rid_to_master(recurrence_id, pt_seg_start)
        split_cmp = pt_split.dt_utc_or_naive
        for ov, _ in self._collect_future_overrides(
            standalone_overrides, pt_seg_start, split_cmp
        ):
            self.components.remove(ov)
        self._truncate_segment_before(
            target_seg, pt_split, pt_seg_start, split_cmp, eff_now
        )
        self._validate_component_state(target_seg)

    def delete(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str = "NONE",
        now: str | None = None,
    ) -> None:
        """Delete a whole series, single occurrence, or THIS_AND_FUTURE range."""
        saved = copy.deepcopy(self.components)
        try:
            norm_range = self._normalize_range(recurrence_range)
            eff_now = canonical_temporal_str(now or DEFAULT_DTSTAMP, "now")
            assert eff_now is not None
            uid_comps, master_comp, recurring_segments, standalone_overrides = (
                self._partition_uid_components(uid)
            )
            if not uid_comps:
                raise StoreError(f"No component found with uid={uid!r}")
            self._reject_legacy_segments(uid_comps)
            if self._is_first_instance_split(recurrence_id, norm_range, master_comp):
                recurrence_id = None

            if recurrence_id is None:
                self._delete_whole_uid_and_children(uid, eff_now)
            elif norm_range == "NONE":
                self._delete_single_instance(
                    recurring_segments, standalone_overrides, recurrence_id, eff_now
                )
            else:
                self._delete_this_and_future(
                    recurring_segments, standalone_overrides, recurrence_id, eff_now
                )
        except Exception:
            self.components = saved
            raise

    def edit(
        self,
        uid: str,
        patch: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str = "NONE",
        now: str | None = None,
        new_uid: str | None = None,
    ) -> None:
        """Edit a whole series, single occurrence, or THIS_AND_FUTURE range.

        `new_uid` names the new segment created by a THIS_AND_FUTURE split at a
        non-first instance (R-L3-001); when omitted a deterministic UID is derived.
        """
        saved = copy.deepcopy(self.components)
        try:
            norm_range = self._normalize_range(recurrence_range)
            self._validate_related_to(patch)
            for t_field in ("dtstart", "dtend", "due", "completed", "dtstamp"):
                if patch.get(t_field) is not None:
                    canonical_temporal_str(patch[t_field], t_field)
            eff_now = canonical_temporal_str(
                patch.get("dtstamp") or now or DEFAULT_DTSTAMP, "dtstamp"
            )
            assert eff_now is not None

            uid_comps, master_comp, recurring_segments, standalone_overrides = (
                self._partition_uid_components(uid)
            )
            if not uid_comps:
                raise StoreError(f"No component found with uid={uid!r}")
            self._reject_legacy_segments(uid_comps)

            normalized_from_first_instance = False
            if self._is_first_instance_split(recurrence_id, norm_range, master_comp):
                recurrence_id = None
                normalized_from_first_instance = True

            if recurrence_id is None:
                self._edit_whole_series(
                    uid,
                    master_comp,
                    standalone_overrides,
                    patch,
                    normalized_from_first_instance,
                    eff_now,
                )
            elif norm_range == "NONE":
                self._edit_single_instance(
                    recurring_segments,
                    standalone_overrides,
                    patch,
                    recurrence_id,
                    eff_now,
                )
            else:
                self._edit_this_and_future(
                    recurring_segments,
                    standalone_overrides,
                    patch,
                    recurrence_id,
                    eff_now,
                    new_uid,
                )
        except Exception:
            self.components = saved
            raise

    @staticmethod
    def _build_timeline_entry(
        uid: str,
        rid_key: str,
        pt_occ: ParsedTemporal,
        dur: datetime.timedelta | None,
        src_comp: dict[str, Any],
        is_recurring_series: bool,
    ) -> dict[str, Any]:
        """Build a complete canonical timeline occurrence dictionary."""
        is_todo = src_comp["type"] == "VTODO"
        end_key = "due" if is_todo else "dtend"
        end_val: str | None = None
        if src_comp.get(end_key) is not None and dur is not None:
            end_val = format_temporal_like(
                add_temporal_duration(
                    pt_occ.value, dur, min_days=(0 if is_todo else 1)
                ),
                pt_occ,
                use_ical_prop=None,
            )
        item: dict[str, Any] = {
            "type": src_comp["type"],
            "uid": uid,
            "recurrence_id": rid_key
            if is_recurring_series
            else src_comp.get("recurrence_id"),
            "summary": src_comp.get("summary"),
            "dtstart": format_temporal_like(pt_occ.value, pt_occ, use_ical_prop=None),
            end_key: end_val,
            "sequence": src_comp.get("sequence"),
            "dtstamp": src_comp.get("dtstamp"),
            "created": src_comp.get("created"),
            "last_modified": src_comp.get("last_modified"),
        }
        if is_todo:
            item["status"] = src_comp.get("status")
            item["completed"] = src_comp.get("completed")
        item["related_to"] = copy.deepcopy(src_comp.get("related_to") or [])
        for k, v in src_comp.items():
            if k not in CORE_COMPONENT_KEYS:
                item[k] = copy.deepcopy(v)
        return item

    def _expand_uid_occurrences(
        self, u_comps: list[dict[str, Any]]
    ) -> tuple[
        dict[str, tuple[ParsedTemporal, datetime.timedelta | None, dict[str, Any]]],
        bool,
    ]:
        """Expand recurring segments and apply standalone overrides for a single UID."""
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
        is_recurring_series = bool(
            any(c.get("rrule") or c.get("rdate") for c in u_comps)
            or standalone_overrides
        )
        expanded_map: dict[
            str, tuple[ParsedTemporal, datetime.timedelta | None, dict[str, Any]]
        ] = {}
        seg_candidates: list[tuple[ParsedTemporal, set[str]]] = []
        for rc in recurring_comps:
            if not rc.get("dtstart"):
                continue
            pt_rc = parse_temporal(rc["dtstart"], "dtstart")
            cand_rids = {
                rid
                for rid, _, _ in expand_component_candidates(rc, include_exdates=True)
            }
            seg_candidates.append((pt_rc, cand_rids))
            for rid_str, pt_occ, dur in expand_component_candidates(
                rc, include_exdates=False
            ):
                expanded_map[rid_str] = (pt_occ, dur, rc)

        for ov in standalone_overrides:
            pt_ov_raw = parse_temporal(ov["recurrence_id"], "recurrence_id")
            owner_pt = next(
                (
                    pt_rc
                    for pt_rc, cand_rids in seg_candidates
                    if pt_ov_raw.is_date == pt_rc.is_date
                    and format_canonical_rid(
                        align_rid_to_master(ov["recurrence_id"], pt_rc)
                    )
                    in cand_rids
                ),
                seg_candidates[0][0] if seg_candidates else None,
            )
            pt_rid = (
                align_rid_to_master(ov["recurrence_id"], owner_pt)
                if owner_pt is not None and pt_ov_raw.is_date == owner_pt.is_date
                else pt_ov_raw
            )
            expanded_map[format_canonical_rid(pt_rid)] = (
                parse_temporal(ov["dtstart"], "dtstart"),
                self._compute_duration(ov),
                ov,
            )
        return expanded_map, is_recurring_series

    def expand_timeline(self) -> list[dict[str, Any]]:
        """Expand all stored VEVENT and VTODO components into a chronologically sorted timeline."""
        comps_by_uid: dict[str, list[dict[str, Any]]] = {}
        for comp in self.components:
            if comp.get("type") != "VTIMEZONE" and (uid := comp.get("uid")):
                comps_by_uid.setdefault(uid, []).append(comp)

        all_occurrences: list[tuple[datetime.datetime, int, dict[str, Any]]] = []
        serial_idx = 0
        for uid, u_comps in comps_by_uid.items():
            expanded_map, is_recurring_series = self._expand_uid_occurrences(u_comps)
            for rid_key, (pt_occ, dur, src_comp) in expanded_map.items():
                item = self._build_timeline_entry(
                    uid, rid_key, pt_occ, dur, src_comp, is_recurring_series
                )
                serial_idx += 1
                all_occurrences.append((pt_occ.dt_utc_or_naive, serial_idx, item))

        all_occurrences.sort(
            key=lambda t: (
                t[0],
                t[2].get("uid", ""),
                t[2].get("recurrence_id") or "",
                t[1],
            )
        )
        return [item for _, _, item in all_occurrences]
