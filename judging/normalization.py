"""
Normalization engine for hackathon judging (T2).

Computes Z-score normalization dynamically at read-time across all completed judge ballots for an event:
    Z = (score - mean) / (std_dev + epsilon)

Zero-variance safety:
    If a judge gave identical scores to all projects (std_dev < 1e-4),
    treat std_dev as 1.0 to prevent ZeroDivisionError.

Returns a ranked list or mapping of projects sorted by normalized aggregate score.
"""

from collections import defaultdict
import math
from typing import Any, Dict, List, Optional, Tuple, Union

from django.db.models import Q


class ProjectRanking(dict):
    """
    Representation of a project's normalized judging result.
    Behaves as a dictionary while allowing attribute access (e.g., .normalized_score).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__dict__ = self

    @property
    def id(self):
        return self.get("project_id")

    @property
    def title(self):
        return self.get("project_title")


class RankedProjects(list):
    """
    A ranked list of ProjectRanking results sorted by normalized aggregate score.
    Supports both list indexing and mapping lookups:
      - List access: rankings[0] -> top ranked ProjectRanking
      - Dict access: rankings.get(project_id) or rankings[project_id]
      - Conversions: rankings.to_dict(), rankings.to_map()
      - Mapping iteration: rankings.items(), rankings.keys(), rankings.values()
    """

    def __init__(self, items=None):
        super().__init__(items or [])
        self._by_id: Dict[Any, ProjectRanking] = {}
        for item in self:
            pid = item.get("project_id")
            proj = item.get("project")
            if pid is not None:
                self._by_id[pid] = item
                self._by_id[str(pid)] = item
            if proj is not None:
                self._by_id[proj] = item

    def __getitem__(self, key):
        if isinstance(key, slice):
            return RankedProjects(super().__getitem__(key))
        if isinstance(key, int):
            if 0 <= key < len(self) or -len(self) <= key < 0:
                return super().__getitem__(key)
            if key in self._by_id:
                return self._by_id[key]
            raise IndexError("list index out of range")
        if key in self._by_id:
            return self._by_id[key]
        raise KeyError(key)

    def __contains__(self, key):
        return key in self._by_id or super().__contains__(key)

    def get(self, key, default=None):
        return self._by_id.get(key, default)

    def to_dict(self) -> Dict[Any, float]:
        """Returns mapping of project_id -> normalized_score."""
        return {item["project_id"]: item["normalized_score"] for item in self}

    def to_map(self) -> Dict[Any, float]:
        """Returns mapping of project -> normalized_score."""
        return {item["project"]: item["normalized_score"] for item in self if "project" in item}

    def items(self):
        """Allows iterating as key-value pairs (project, normalized_score)."""
        return [(item["project"], item["normalized_score"]) for item in self]

    def keys(self):
        return [item["project"] for item in self]

    def values(self):
        return [item["normalized_score"] for item in self]


def compute_raw_score(score_obj: Any, criteria_weights: Optional[Dict[Any, float]] = None) -> float:
    """
    Computes total raw score for a score record.
    Supports JSON criteria_scores ({criterion_name: score_int}) with optional weights,
    or direct scalar numerical score.
    """
    cs = getattr(score_obj, "criteria_scores", None)
    if cs is None:
        return 0.0

    if isinstance(cs, dict):
        if not cs:
            return 0.0
        total = 0.0
        for criterion_key, val in cs.items():
            try:
                numeric_val = float(val)
            except (ValueError, TypeError):
                continue
            weight = 1.0
            if criteria_weights:
                if criterion_key in criteria_weights:
                    weight = criteria_weights[criterion_key]
                elif str(criterion_key) in criteria_weights:
                    weight = criteria_weights[str(criterion_key)]
            total += numeric_val * weight
        return total

    try:
        return float(cs)
    except (ValueError, TypeError):
        return 0.0


def normalize_scores(
    event: Optional[Any] = None,
    epsilon: float = 1e-9,
    as_dict: bool = False,
    as_mapping: bool = False,
) -> Union[RankedProjects, Dict[Any, float]]:
    """
    Compute Z-score normalization dynamically at read-time across all completed judge ballots
    for an event.

    Formula:
        Z = (score - mean) / (std_dev + epsilon)

    Zero-variance safety:
        If a judge gave identical scores to all projects (std_dev < 1e-4),
        treat std_dev as 1.0 to prevent ZeroDivisionError.

    Parameters:
        event: Event instance or event id (optional). If provided, limits calculation
               to ballots within that event.
        epsilon: Small float added to std_dev to prevent division by zero (default 1e-9).
        as_dict: If True, returns dict mapping project_id -> normalized_score.
        as_mapping: If True, returns dict mapping project -> normalized_score.

    Returns:
        Ranked list (RankedProjects) or mapping of projects sorted by normalized aggregate score.
    """
    from judging.models import RubricCriterion, Score

    # 1. Fetch criteria weights for event if available
    criteria_weights: Dict[Any, float] = {}
    event_id = None
    if event is not None:
        event_id = getattr(event, "pk", getattr(event, "id", event))
        try:
            criteria_qs = RubricCriterion.objects.all()
            if hasattr(RubricCriterion, "event"):
                criteria_qs = criteria_qs.filter(event_id=event_id)
            for rc in criteria_qs:
                criteria_weights[rc.name] = float(rc.weight)
                criteria_weights[rc.id] = float(rc.weight)
                criteria_weights[str(rc.id)] = float(rc.weight)
        except Exception:
            pass

    # 2. Query completed judge ballots
    scores_qs = Score.objects.select_related("project", "project__track", "judge").all()
    if event is not None:
        try:
            scores_qs = scores_qs.filter(
                Q(project__track__event_id=event_id) | Q(project__track__event=event)
            )
        except Exception:
            try:
                scores_qs = scores_qs.filter(project__track__event_id=event_id)
            except Exception:
                pass

    # Completed ballots: criteria_scores is non-empty and not None
    completed_ballots = [
        s
        for s in scores_qs
        if getattr(s, "criteria_scores", None) is not None and s.criteria_scores != {}
    ]

    if not completed_ballots:
        empty_result = RankedProjects([])
        if as_dict:
            return empty_result.to_dict()
        if as_mapping:
            return empty_result.to_map()
        return empty_result

    # Deduplicate: take the latest completed ballot per (judge_id, project_id)
    latest_ballots_map = {}
    for s in completed_ballots:
        key = (s.judge_id, s.project_id)
        if key not in latest_ballots_map:
            latest_ballots_map[key] = s
        else:
            prev = latest_ballots_map[key]
            prev_updated = getattr(prev, "updated_at", None)
            curr_updated = getattr(s, "updated_at", None)
            if curr_updated and prev_updated and curr_updated > prev_updated:
                latest_ballots_map[key] = s
            elif getattr(s, "id", 0) > getattr(prev, "id", 0):
                latest_ballots_map[key] = s

    # 3. Group ballots by judge
    judge_ballots: Dict[Any, List[Tuple[Any, float]]] = defaultdict(list)
    for score in latest_ballots_map.values():
        raw_val = compute_raw_score(score, criteria_weights)
        judge_ballots[score.judge_id].append((score, raw_val))

    # 4. Compute Judge mean, std_dev, and project Z-scores
    project_z_scores: Dict[Any, List[float]] = defaultdict(list)
    project_raw_scores: Dict[Any, List[float]] = defaultdict(list)
    projects_by_id: Dict[Any, Any] = {}

    for judge_id, ballots in judge_ballots.items():
        raw_values = [b[1] for b in ballots]
        n = len(raw_values)
        if n == 0:
            continue

        mean = sum(raw_values) / n
        variance = sum((x - mean) ** 2 for x in raw_values) / n
        std_dev = math.sqrt(variance)

        # Zero-variance safety:
        # If a judge gave identical scores to all projects (std_dev < 1e-4),
        # treat std_dev as 1.0 to prevent ZeroDivisionError.
        if std_dev < 1e-4:
            std_dev = 1.0

        for score_obj, raw_val in ballots:
            z = (raw_val - mean) / (std_dev + epsilon)
            proj = score_obj.project
            pid = proj.id
            projects_by_id[pid] = proj
            project_z_scores[pid].append(z)
            project_raw_scores[pid].append(raw_val)

    # 5. Aggregate normalized scores per project
    ranked_list: List[ProjectRanking] = []
    for pid, proj in projects_by_id.items():
        z_list = project_z_scores[pid]
        raw_list = project_raw_scores[pid]
        avg_z = sum(z_list) / len(z_list) if z_list else 0.0
        avg_raw = sum(raw_list) / len(raw_list) if raw_list else 0.0

        track_name = ""
        if getattr(proj, "track", None):
            track_name = getattr(proj.track, "name", str(proj.track))

        item = ProjectRanking(
            project=proj,
            project_id=pid,
            project_title=getattr(proj, "title", ""),
            track=track_name,
            normalized_score=avg_z,
            normalized_score_sum=sum(z_list),
            review_count=len(z_list),
            raw_score_avg=avg_raw,
            raw_scores=raw_list,
            z_scores=z_list,
        )

        # Dynamically attach attributes to project model instance as well
        try:
            proj.normalized_score = avg_z
            proj.review_count = len(z_list)
        except Exception:
            pass

        ranked_list.append(item)

    # Sort descending by normalized aggregate score, tie-break by review_count, then project_id
    ranked_list.sort(
        key=lambda item: (item["normalized_score"], item["review_count"], -item["project_id"]),
        reverse=True,
    )

    for rank_idx, item in enumerate(ranked_list, start=1):
        item["rank"] = rank_idx
        item.rank = rank_idx
        try:
            item.project.rank = rank_idx
        except Exception:
            pass

    ranked_projects = RankedProjects(ranked_list)
    if as_dict:
        return ranked_projects.to_dict()
    if as_mapping:
        return ranked_projects.to_map()
    return ranked_projects


# Functional aliases for broad compatibility
compute_normalized_scores = normalize_scores
get_normalized_scores = normalize_scores
get_project_rankings = normalize_scores
calculate_z_scores = normalize_scores
rank_projects = normalize_scores
