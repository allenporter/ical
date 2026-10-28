"""Clean-room Reference Store Oracle for iCalendar / CalDAV recurrence and editing semantics.

Implements a 100% standalone, RFC-grounded reference state machine and timeline expander
covering all 38 specification rules (R-L1-001 through R-L5-008, including whole-series
delete R-L4-001 and single-instance delete R-L2-001, R-L2-002) and configurable store
policies (`PolicyConfig`) using ONLY the Python standard library and `dateutil.rrule`.
"""

from __future__ import annotations

import copy
import datetime
from typing import Any

from .oracle_edit import OracleEditMixin
from .oracle_temporal import (
    ParentDeleteCascadeMode,
    ParsedTemporal,
    PolicyConfig,
    SeriesEditOverrideMode,
    SeriesRescheduleExceptionMode,
    SingleEditExdateMode,
    SplitFutureOverrideMode,
    StoreError,
    ThisAndFutureSplitMode,
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
    "ThisAndFutureSplitMode",
    "align_rid_to_master",
    "compute_until_string",
    "execute_scenario",
    "expand_component_candidates",
    "format_canonical_rid",
    "format_temporal_like",
    "parse_temporal",
    "replace_rrule_count",
    "replace_rrule_until",
]


class ReferenceStore(OracleEditMixin):
    """Clean-room Reference Store Oracle implementing R-L1-001 through R-L5-008."""

    def add(
        self,
        item: dict[str, Any],
        default_type: str | None = None,
        now: str = "2025-01-01T00:00:00Z",
        serialize_ical_tzid: bool = False,
    ) -> dict[str, Any]:
        """Add a new VEVENT or VTODO component to the store (R-L5-001, R-L5-004..R-L5-007)."""
        new_comp = copy.deepcopy(item)
        self._validate_related_to(new_comp)
        ctype = new_comp.get("type") or default_type
        is_todo = ctype == "VTODO" or "due" in new_comp or "status" in new_comp

        if is_todo and not new_comp.get("dtstart") and new_comp.get("due"):
            pt_due = parse_temporal(new_comp["due"], "due")
            new_comp["dtstart"] = format_temporal_like(
                pt_due.value - datetime.timedelta(days=1), pt_due
            )

        pt_start = self._validate_and_register_timezone(
            new_comp.get("dtstart"), "dtstart"
        )
        pt_end = self._validate_and_register_timezone(new_comp.get("dtend"), "dtend")
        self._validate_and_register_timezone(new_comp.get("due"), "due")

        if serialize_ical_tzid:
            if pt_start and pt_start.kind == "TZID":
                new_comp["dtstart"] = format_temporal_like(
                    pt_start.value, pt_start, use_ical_prop="DTSTART"
                )
            if pt_end and pt_end.kind == "TZID":
                new_comp["dtend"] = format_temporal_like(
                    pt_end.value, pt_end, use_ical_prop="DTEND"
                )

        out_comp: dict[str, Any] = {}
        if ctype is not None or (pt_start and pt_start.kind == "TZID"):
            out_comp["type"] = ctype or ("VTODO" if is_todo else "VEVENT")
        out_comp["uid"] = new_comp["uid"]
        for k in ("summary", "dtstart", "dtend", "due"):
            if k in new_comp:
                out_comp[k] = new_comp[k]
        for k, v in new_comp.items():
            if k not in out_comp and k not in (
                "dtstamp",
                "created",
                "sequence",
                "last_modified",
            ):
                out_comp[k] = v

        if any(k in new_comp for k in ("dtstamp", "created", "sequence")):
            dtstamp_val = new_comp.get("dtstamp") or now
            out_comp["dtstamp"] = dtstamp_val
            out_comp["created"] = new_comp.get("created") or dtstamp_val
            out_comp["sequence"] = (
                new_comp["sequence"] if new_comp.get("sequence") is not None else 0
            )
            out_comp["last_modified"] = new_comp.get("last_modified", None)

        if (
            is_todo
            and new_comp.get("status") == "COMPLETED"
            and not out_comp.get("completed")
        ):
            out_comp["completed"] = out_comp.get("dtstamp") or now

        self.components.append(out_comp)
        return out_comp

    def _delete_single_instance(
        self,
        recurring_segments: list[dict[str, Any]],
        standalone_overrides: list[dict[str, Any]],
        recurrence_id: str,
        now: str | None,
    ) -> None:
        """Delete a single instance (Range=NONE) (R-L2-001, R-L2-002, R-L5-003)."""
        target_seg = self._find_segment_for_rid(recurring_segments, recurrence_id)
        if target_seg is None:
            return
        pt_seg_start = parse_temporal(target_seg["dtstart"], "dtstart")
        pt_rid = align_rid_to_master(recurrence_id, pt_seg_start)
        canon_rid = format_canonical_rid(pt_rid)

        for ov in standalone_overrides:
            if (
                format_canonical_rid(
                    align_rid_to_master(ov["recurrence_id"], pt_seg_start)
                )
                == canon_rid
            ):
                self.components.remove(ov)

        exdate_list = list(target_seg.get("exdate") or [])
        existing_ex_rids = {
            format_canonical_rid(parse_temporal(x, "exdate")) for x in exdate_list
        }
        exdate_added = canon_rid not in existing_ex_rids
        if exdate_added:
            exdate_list.append(format_temporal_like(pt_rid.value, pt_seg_start))
        target_seg["exdate"] = exdate_list

        if exdate_added:
            if "sequence" in target_seg or "dtstamp" in target_seg or now is not None:
                old_seq = target_seg.get("sequence") or 0
                target_seg["sequence"] = old_seq + 1 if old_seq else 1
            if now is not None or "dtstamp" in target_seg:
                eff_now = now or target_seg.get("dtstamp") or "2025-01-01T00:00:00Z"
                target_seg["dtstamp"] = eff_now
                target_seg["last_modified"] = eff_now

    def _delete_this_and_future(
        self,
        uid_comps: list[dict[str, Any]],
        recurring_segments: list[dict[str, Any]],
        recurrence_id: str,
        now: str | None,
    ) -> None:
        """Delete THIS_AND_FUTURE range after the first instance (R-L3-003, R-L3-006..R-L3-008)."""
        target_seg = self._find_segment_for_rid(recurring_segments, recurrence_id)
        if target_seg is None:
            return
        pt_seg_start = parse_temporal(target_seg["dtstart"], "dtstart")
        pt_split = align_rid_to_master(recurrence_id, pt_seg_start)
        split_cmp = pt_split.dt_utc_or_naive
        is_seg_start = self._targets_seg_start(target_seg, recurrence_id)
        cutoff_cmp = self._segment_cutoff_cmp(
            target_seg, pt_seg_start, split_cmp, is_seg_start
        )

        for c in list(uid_comps):
            if c is not target_seg and c.get("recurrence_id") is not None:
                if (
                    align_rid_to_master(
                        c["recurrence_id"], pt_seg_start
                    ).dt_utc_or_naive
                    >= cutoff_cmp
                ):
                    self.components.remove(c)

        if is_seg_start:
            self.components.remove(target_seg)
            return

        self._truncate_segment_before(target_seg, pt_split, pt_seg_start, split_cmp)
        if "sequence" in target_seg and "recurrence_id" not in target_seg:
            self._insert_key_after(target_seg, "uid", "recurrence_id", None)

        if "sequence" in target_seg or "dtstamp" in target_seg or now is not None:
            old_seq = target_seg.get("sequence") or 0
            target_seg["sequence"] = old_seq + 1 if old_seq else 1
        if now is not None or "dtstamp" in target_seg:
            eff_now = now or target_seg.get("dtstamp") or "2025-01-01T00:00:00Z"
            target_seg["dtstamp"] = eff_now
            target_seg["last_modified"] = eff_now

    def delete(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str = "NONE",
        now: str | None = None,
    ) -> None:
        """Delete a whole series, single occurrence, or THIS_AND_FUTURE range."""
        norm_range = (
            "THIS_AND_FUTURE"
            if recurrence_range in ("THIS_AND_FUTURE", "THISANDFUTURE")
            else "NONE"
        )
        uid_comps, master_comp, recurring_segments, standalone_overrides = (
            self._partition_uid_components(uid)
        )
        if not uid_comps:
            return
        if self._is_first_instance_split(recurrence_id, norm_range, master_comp):
            recurrence_id = None

        if recurrence_id is None:
            cascade_mode = self.policy.parent_delete_cascade_mode
            self.components = [
                c
                for c in self.components
                if not (
                    c.get("type") != "VTIMEZONE"
                    and (
                        c.get("uid") == uid
                        or (
                            cascade_mode == ParentDeleteCascadeMode.CASCADE_DELETE
                            and any(
                                rel.get("uid") == uid and self._is_parent_relation(rel)
                                for rel in (c.get("related_to") or [])
                            )
                        )
                    )
                )
            ]
            if cascade_mode == ParentDeleteCascadeMode.DETACH_CHILDREN:
                for c in self.components:
                    if c.get("related_to"):
                        c["related_to"] = [
                            rel
                            for rel in c["related_to"]
                            if not (
                                rel.get("uid") == uid and self._is_parent_relation(rel)
                            )
                        ]
            return

        if norm_range == "NONE":
            self._delete_single_instance(
                recurring_segments, standalone_overrides, recurrence_id, now
            )
        else:
            self._delete_this_and_future(
                uid_comps, recurring_segments, recurrence_id, now
            )

    def edit(
        self,
        uid: str,
        patch: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str = "NONE",
        now: str | None = None,
        append_override_at_end: bool = False,
    ) -> None:
        """Edit a whole series, single occurrence, or THIS_AND_FUTURE range."""
        norm_range = (
            "THIS_AND_FUTURE"
            if recurrence_range in ("THIS_AND_FUTURE", "THISANDFUTURE")
            else "NONE"
        )
        self._validate_related_to(patch)
        for field in ("dtstart", "dtend", "due"):
            self._validate_and_register_timezone(patch.get(field), field)

        uid_comps, master_comp, recurring_segments, standalone_overrides = (
            self._partition_uid_components(uid)
        )
        if not uid_comps:
            return

        normalized_from_first_instance = False
        if self._is_first_instance_split(recurrence_id, norm_range, master_comp):
            recurrence_id = None
            normalized_from_first_instance = True

        if recurrence_id is None:
            self._edit_whole_series(
                uid,
                uid_comps,
                master_comp,
                recurring_segments,
                standalone_overrides,
                patch,
                normalized_from_first_instance,
                now,
            )
        elif norm_range == "NONE":
            self._edit_single_instance(
                master_comp,
                recurring_segments,
                standalone_overrides,
                patch,
                recurrence_id,
                now,
                append_override_at_end,
            )
        else:
            self._edit_this_and_future(
                uid_comps, recurring_segments, patch, recurrence_id, now
            )

    @staticmethod
    def _build_timeline_entry(
        uid: str,
        rid_key: str,
        pt_occ: ParsedTemporal,
        dur: datetime.timedelta | None,
        src_comp: dict[str, Any],
        is_recurring_series: bool,
        *,
        include_end: bool,
        include_recurrence_id: bool,
        include_summary: bool,
        include_sequence: bool,
        include_status_completed: bool,
    ) -> dict[str, Any]:
        """Build a single projected timeline occurrence dictionary."""
        item: dict[str, Any] = {"uid": uid}
        if include_recurrence_id:
            item["recurrence_id"] = rid_key if is_recurring_series else None
        if include_summary and "summary" in src_comp and not include_recurrence_id:
            item["summary"] = src_comp["summary"]
        if not include_status_completed:
            item["dtstart"] = (
                format_temporal_like(pt_occ.value, pt_occ, use_ical_prop=None)
                if pt_occ.prop_prefix
                else pt_occ.raw
            )
        if include_end:
            end_key = "due" if "due" in src_comp else "dtend"
            if end_key in src_comp and dur is not None:
                item[end_key] = format_temporal_like(
                    pt_occ.value + dur, pt_occ, use_ical_prop=None
                )
        if include_summary and "summary" in src_comp and include_recurrence_id:
            item["summary"] = src_comp["summary"]
        if include_sequence and "sequence" in src_comp:
            item["sequence"] = src_comp["sequence"]
        if include_status_completed:
            if "status" in src_comp:
                item["status"] = src_comp["status"]
            if "completed" in src_comp:
                item["completed"] = src_comp["completed"]
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
        master_dtstart_pt: ParsedTemporal | None = None
        for rc in recurring_comps:
            if not rc.get("dtstart"):
                continue
            if master_dtstart_pt is None:
                master_dtstart_pt = parse_temporal(rc["dtstart"], "dtstart")
            for rid_str, pt_occ, dur in expand_component_candidates(
                rc, include_exdates=False
            ):
                expanded_map[rid_str] = (pt_occ, dur, rc)

        for ov in standalone_overrides:
            pt_rid = (
                align_rid_to_master(ov["recurrence_id"], master_dtstart_pt)
                if master_dtstart_pt is not None
                else parse_temporal(ov["recurrence_id"], "recurrence_id")
            )
            expanded_map[format_canonical_rid(pt_rid)] = (
                parse_temporal(ov["dtstart"], "dtstart"),
                self._compute_duration(ov),
                ov,
            )
        return expanded_map, is_recurring_series

    def expand_timeline(
        self,
        include_end: bool = True,
        include_recurrence_id: bool = True,
        include_summary: bool = True,
        include_sequence: bool = False,
        include_status_completed: bool = False,
    ) -> list[dict[str, Any]]:
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
                    uid,
                    rid_key,
                    pt_occ,
                    dur,
                    src_comp,
                    is_recurring_series,
                    include_end=include_end,
                    include_recurrence_id=include_recurrence_id,
                    include_summary=include_summary,
                    include_sequence=include_sequence,
                    include_status_completed=include_status_completed,
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


from .scenario_runner import execute_scenario  # noqa: E402, pylint: disable=wrong-import-position
