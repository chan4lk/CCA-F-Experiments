import json
from dataclasses import dataclass, field


def finding(**overrides):
    base = {
        "file": "src/orders.py",
        "line": 42,
        "category": "security",
        "severity": "blocking",
        "issue": "order_id is interpolated into the SQL string.",
        "failure_input": "order_id = \"1 OR 1=1\"",
        "suggested_fix": "Pass order_id as a query parameter.",
        "detected_pattern": "fstring-in-execute",
    }
    base.update(overrides)
    return base


@dataclass
class Completed:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@dataclass
class FakeCLI:
    """Stands in for subprocess.run. Records every command so the flags that make the
    CLI usable in CI at all (-p, json output, the schema) can be asserted."""

    payloads: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    prompts: list = field(default_factory=list)
    returncode: int = 0
    stderr: str = ""

    def __call__(self, command, input=None, capture_output=False, text=False, timeout=None, check=False):
        self.commands.append(command)
        self.prompts.append(input)
        if self.returncode:
            return Completed(returncode=self.returncode, stderr=self.stderr)
        payload = self.payloads.pop(0) if self.payloads else {"findings": []}
        if isinstance(payload, str):
            return Completed(stdout=payload)
        return Completed(stdout=json.dumps({"type": "result", "is_error": False, "result": payload}))


@dataclass
class FakeGit:
    names: list = field(default_factory=list)
    diff: str = "@@ -1 +1 @@\n-old\n+new"

    def __call__(self, command, capture_output=False, text=False, check=False):
        if "--name-only" in command:
            return Completed(stdout="\n".join(self.names) + "\n")
        return Completed(stdout=self.diff)
