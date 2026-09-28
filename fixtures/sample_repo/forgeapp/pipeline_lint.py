"""Static checks for the CI/CD pipeline definition."""


def lint_stages(stages: list[dict]) -> list[str]:
    """Return a list of human-readable violations (empty means valid)."""
    problems = []
    names = [s.get("name") for s in stages]
    if "test" not in names:
        problems.append("pipeline has no test stage")
    if "deploy" in names and "test" in names and names.index("deploy") < names.index("test"):
        problems.append("deploy runs before test")
    for stage in stages:
        if stage.get("name") == "deploy" and stage.get("approval") != "required":
            problems.append("deploy stage must require approval")
    return problems
