#!/usr/bin/env bash
# Validate all skills in the skills/ directory.
# Usage: bash skills/skill_guide/scripts/validate_all_skills.sh

set -euo pipefail

SKILLS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
errors=0

for skill_dir in "$SKILLS_DIR"/*/; do
    skill_name=$(basename "$skill_dir")
    skill_md="$skill_dir/SKILL.md"

    if [ ! -f "$skill_md" ]; then
        echo "FAIL  $skill_name: SKILL.md missing"
        errors=$((errors + 1))
        continue
    fi

    if ! head -1 "$skill_md" | grep -q "^---"; then
        echo "FAIL  $skill_name: no YAML frontmatter"
        errors=$((errors + 1))
        continue
    fi

    if ! grep -q "^name:" "$skill_md"; then
        echo "FAIL  $skill_name: frontmatter missing 'name'"
        errors=$((errors + 1))
    fi

    if ! grep -q "^description:" "$skill_md"; then
        echo "FAIL  $skill_name: frontmatter missing 'description'"
        errors=$((errors + 1))
    fi

    tools_py="$skill_dir/tools.py"
    if [ -f "$tools_py" ]; then
        if grep -q "^TOOLS = \[" "$tools_py"; then
            echo "WARN  $skill_name: tools.py uses legacy TOOLS array"
        fi
    fi

    echo "OK    $skill_name"
done

if [ $errors -gt 0 ]; then
    echo ""
    echo "$errors error(s) found"
    exit 1
else
    echo ""
    echo "All skills passed validation"
fi
