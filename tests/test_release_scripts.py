"""The release scripts must not publish a tag before CI has judged the commit.

v2.17.0 shipped a default install that returned 401 against its own machine.
Nothing stopped it: the tag was pushed seconds after the release commit, long
before any workflow finished, so a green suite arrived after the release was
already public. The install-defaults job now covers that path, but a passing
job only helps if the tag waits for it.

These tests pin the ORDERING, which is the property that matters - a gate that
runs after the tag push would pass a naive "does it mention CI" check.
"""

import pytest


def _read(path: str) -> str:
    # Explicit encoding: the scripts print checkmarks, and Windows CI defaults
    # to cp1252 (see tests/test_docker_compose.py for the same trap).
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(params=["release.sh", "release-lite.sh"])
def script(request):
    return request.param, _read(request.param)


class TestCIGate:
    def test_gate_exists(self, script):
        name, body = script
        assert "SKIP_CI_GATE" in body, f"{name} has no CI gate"
        assert "gh run list --commit" in body, \
            f"{name} does not consult CI for the release commit"

    def test_tag_push_comes_after_the_gate(self, script):
        """The seam: main is pushed, CI judges it, only then does the tag go."""
        name, body = script
        main_push = body.index("git push origin main")
        gate = body.index("gh run list --commit")
        tag_push = body.index('git push origin "v$NEW_VERSION"')
        assert main_push < gate, f"{name} must push the commit before waiting on CI"
        assert gate < tag_push, (
            f"{name} pushes the tag before the CI gate - the tag is what "
            f"publishes a release, so it must be last"
        )

    def test_gate_failure_does_not_push_the_tag(self, script):
        """A red CI must exit, not warn and carry on."""
        name, body = script
        tail = body[body.index("gh run list --commit"):body.index('git push origin "v$NEW_VERSION"')]
        assert "exit 1" in tail, f"{name} does not abort when CI is red"

    def test_escape_hatch_is_explicit(self, script):
        """An emergency override is fine; a silent one is not."""
        name, body = script
        assert "--skip-ci-gate" in body, f"{name} has no documented override"


class TestMisleadingJobName:
    def test_windows_job_does_not_claim_to_verify_a_released_msi(self):
        """It builds the installer from source, with the unpatched main ref.

        A release MSI has DEFAULT_REPO_REF rewritten to its tag by the build
        workflow, so a locally built one exercises a different path from the
        artifact customers install.
        """
        wf = _read(".github/workflows/test-windows.yml")
        assert "name: MSI Install Verification" not in wf, \
            "job name implies it installs a released MSI; it builds one from source"
