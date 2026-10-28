
def build_recommendations(student):
    """
    Generate rule-based career recommendations from a student's skills.

    The student object is expected to expose a `skills` attribute
    containing skill names, or a collection of student-skill records.
    """

    career_profiles = [
        {
            "career": "Data Analyst",
            "required_skills": {
                "python",
                "sql",
                "statistics",
                "data visualization",
            },
        },
        {
            "career": "Machine Learning Engineer",
            "required_skills": {
                "python",
                "machine learning",
                "statistics",
                "sql",
            },
        },
        {
            "career": "Backend Developer",
            "required_skills": {
                "python",
                "sql",
                "api development",
                "git",
            },
        },
    ]

    raw_skills = getattr(student, "skills", []) or []
    student_skills = set()

    for item in raw_skills:
        if isinstance(item, str):
            skill_name = item
        else:
            skill_name = getattr(item, "name", None)

            if skill_name is None:
                skill = getattr(item, "skill", None)
                skill_name = getattr(skill, "name", None)

        if skill_name:
            student_skills.add(skill_name.strip().lower())

    recommendations = []

    for profile in career_profiles:
        required = profile["required_skills"]
        matched = sorted(required & student_skills)
        missing = sorted(required - student_skills)

        match_percentage = round(
            len(matched) / len(required) * 100
        )

        recommendations.append(
            {
                "career": profile["career"],
                "match_percentage": match_percentage,
                "matched_skills": matched,
                "missing_skills": missing,
            }
        )

    recommendations.sort(
        key=lambda item: item["match_percentage"],
        reverse=True,
    )

    return recommendations
