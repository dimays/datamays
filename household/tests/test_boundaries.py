"""The dependency rules between household and finance, enforced (ADR 0009).

- finance may import only the shell's modules from household.
- household reaches finance only through `household/integrations/finance.py`.

Tests are exempt on both sides — they build whatever data they need — and so
is the local demo seed, which exists to build finance data.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# The household modules finance is allowed to depend on: the shell. Anything
# about chores, projects, or maintenance is deliberately absent.
SHELL_MODULES = {
    "household.access",
    "household.dates",
    "household.forms.base",
    "household.redirects",
    "household.views.base",
}

FINANCE_BRIDGE = "household/integrations/finance.py"
BRIDGE_EXEMPT = {FINANCE_BRIDGE, "household/services/demo.py"}


def imported_modules(path):
    """Absolute module names a file imports, relative imports resolved."""
    package = ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts[:-1])
    names = set()

    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[: len(package.split(".")) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module
            names.add(module)
            # `from household import access` names the module in the alias.
            names.update(f"{module}.{alias.name}" for alias in node.names)

    return names


def source_files(app):
    return [
        path
        for path in (REPO_ROOT / app).rglob("*.py")
        if "tests" not in path.relative_to(REPO_ROOT).parts
        and "migrations" not in path.relative_to(REPO_ROOT).parts
    ]


class BoundaryTests(SimpleTestCase):
    def test_finance_depends_only_on_the_shell(self):
        def allowed(module):
            # `from household.dates import household_today` records both the
            # module and `household.dates.household_today`.
            return module in SHELL_MODULES or module.rsplit(".", 1)[0] in SHELL_MODULES

        offenders = [
            f"{path.relative_to(REPO_ROOT)} imports {module}"
            for path in source_files("finance")
            for module in imported_modules(path)
            if module.startswith("household.") and not allowed(module)
        ]

        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_household_reaches_finance_only_through_the_bridge(self):
        offenders = []

        for path in source_files("household"):
            relative = str(path.relative_to(REPO_ROOT))
            if relative in BRIDGE_EXEMPT:
                continue
            for module in imported_modules(path):
                if module == "finance" or module.startswith("finance."):
                    offenders.append(f"{relative} imports {module}")

        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_rules_would_catch_a_violation(self):
        """Guards the parser: a test that can never fail proves nothing."""
        sample = REPO_ROOT / "household" / "views" / "today.py"

        self.assertIn("household.integrations.finance", imported_modules(sample))
        self.assertIn("household.models", imported_modules(sample))


class FinanceFieldContractTests(SimpleTestCase):
    """The bridge hands back finance's own Transaction objects, and household
    templates and services read these fields from them. A finance rename
    would otherwise fail silently in a template; it fails here instead.
    Round-1 review: ADR 0009 overstated what the single import guarded."""

    FIELDS_HOUSEHOLD_READS = {
        "Transaction": ["amount", "posted_on", "merchant", "description_raw", "is_transfer", "account", "category"],
        "Account": ["name"],
        "Category": ["name", "slug", "kind"],
    }

    def test_every_field_household_reads_exists(self):
        from finance import models as finance_models

        for model_name, fields in self.FIELDS_HOUSEHOLD_READS.items():
            model = getattr(finance_models, model_name)
            names = {field.name for field in model._meta.get_fields()}
            for field in fields:
                with self.subTest(model=model_name, field=field):
                    self.assertIn(field, names)
