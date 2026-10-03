from app.matching import eligibility_reason, score_job


def test_good_junior_backend_match():
    ok, _ = eligibility_reason(
        "Développeur backend Python junior",
        "CDI, FastAPI, PostgreSQL, Git, bac+5",
        "Strasbourg",
        "CDI",
        "France Travail",
    )
    result = score_job(
        "Développeur backend Python junior",
        "CDI, FastAPI, PostgreSQL, Git, bac+5",
        "Strasbourg",
        "CDI",
    )
    assert ok
    assert result["score"] >= 70
    assert "python" in result["matched_skills"]


def test_senior_is_rejected():
    ok, reason = eligibility_reason(
        "Senior Python Lead", "Python SQL CDI", "Paris", "CDI", "France Travail"
    )
    assert not ok
    assert "senior" in reason


def test_internship_is_rejected():
    ok, _ = eligibility_reason(
        "Data Analyst junior", "Power BI SQL", "Paris", "stage", "France Travail"
    )
    assert not ok


def test_non_french_international_offer_is_rejected():
    ok, reason = eligibility_reason(
        "Junior Python developer", "Python SQL", "USA, Canada", "full_time", "Remotive"
    )
    assert not ok
    assert "France" in reason


def test_three_years_experience_is_rejected():
    ok, reason = eligibility_reason(
        "Développeur Python", "3 ans d'expérience exigés, Python SQL", "Paris", "CDI", "France Travail"
    )
    assert not ok
    assert "3 ans" in reason


def test_experience_threshold_phrasings_are_rejected():
    for phrase in ("minimum 3 ans d'expérience", "3+ years", "3 à 5 ans d'expérience", "4 ans requis"):
        ok, _ = eligibility_reason("Data Analyst junior", phrase, "Paris", "CDI", "France Travail")
        assert not ok, phrase
