from desktop_app.utils.search_limits import candidate_limit_for_unique_files


def test_candidate_limit_for_unique_files_matches_desktop_search_windows():
    assert candidate_limit_for_unique_files(1) == 51
    assert candidate_limit_for_unique_files(5) == 100
    assert candidate_limit_for_unique_files(10) == 200
    assert candidate_limit_for_unique_files(25) == 500
    assert candidate_limit_for_unique_files(None) is None
