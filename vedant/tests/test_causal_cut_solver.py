from app.optimizer.causal_cut_solver import CandidateIntervention, solve_minimum_causal_cut


def test_picks_cheapest_single_covering_action():
    candidates = [
        CandidateIntervention("cheap", "suspend_permit", 0.1, 10, frozenset({"HE-042"})),
        CandidateIntervention("expensive", "evacuate_workers", 0.6, 120, frozenset({"HE-042"})),
    ]
    result = solve_minimum_causal_cut(candidates, active_paths={"HE-042"})
    assert result.status == "OPTIMAL"
    assert result.chosen_ids == ["cheap"]


def test_one_action_can_cover_multiple_paths_cheaper_than_two():
    candidates = [
        CandidateIntervention("close_zone", "close_zone", 0.3, 60, frozenset({"HE-042", "HE-043"})),
        CandidateIntervention("fix_042", "suspend_permit", 0.2, 10, frozenset({"HE-042"})),
        CandidateIntervention("fix_043", "isolate_equipment", 0.2, 15, frozenset({"HE-043"})),
    ]
    result = solve_minimum_causal_cut(candidates, active_paths={"HE-042", "HE-043"})
    assert result.chosen_ids == ["close_zone"]


def test_incompatible_pair_never_both_chosen():
    candidates = [
        CandidateIntervention("a", "evacuate_workers", 0.1, 10, frozenset({"HE-042"}), incompatible_with=frozenset({"b"})),
        CandidateIntervention("b", "continue_hot_work", 0.05, 5, frozenset({"HE-042"}), incompatible_with=frozenset({"a"})),
    ]
    result = solve_minimum_causal_cut(candidates, active_paths={"HE-042"})
    assert not ({"a", "b"} <= set(result.chosen_ids))


def test_latency_ceiling_excludes_slow_actions():
    candidates = [
        CandidateIntervention("slow", "evacuate_workers", 0.05, 300, frozenset({"HE-042"})),
        CandidateIntervention("fast", "suspend_permit", 0.3, 10, frozenset({"HE-042"})),
    ]
    result = solve_minimum_causal_cut(candidates, active_paths={"HE-042"}, max_latency_s=60)
    assert result.chosen_ids == ["fast"]


def test_uncoverable_path_is_reported_not_hidden():
    candidates = [CandidateIntervention("a", "suspend_permit", 0.1, 10, frozenset({"HE-042"}))]
    result = solve_minimum_causal_cut(candidates, active_paths={"HE-042", "HE-999"})
    assert "HE-999" in result.uncovered_paths
    assert result.chosen_ids == ["a"]


def test_no_candidates_returns_no_candidates_status():
    result = solve_minimum_causal_cut([], active_paths={"HE-042"})
    assert result.status == "NO_CANDIDATES"

