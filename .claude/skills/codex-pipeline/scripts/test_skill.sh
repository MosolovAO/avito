#!/usr/bin/env bash
# Структурная проверка skill codex-pipeline: защита явной активации и обязательных инструкций.
# Запуск: bash .claude/skills/codex-pipeline/scripts/test_skill.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"
SKILL="$SKILL_DIR/SKILL.md"
BRIEF="$SKILL_DIR/references/task-brief.md"
PASS=0
FAIL=0

check() {
  desc="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    PASS=$((PASS + 1))
    echo "ok   - $desc"
  else
    FAIL=$((FAIL + 1))
    echo "FAIL - $desc"
  fi
}

# Строки между первыми двумя «---» файла.
frontmatter() {
  awk 'NR == 1 && $0 != "---" { exit 1 } NR > 1 && $0 == "---" { exit } NR > 1 { print }' "$1"
}

has() { grep -qF -- "$2" "$1"; }
fm_has() { frontmatter "$1" | grep -qxF -- "$2"; }

check "SKILL.md существует" test -f "$SKILL"
check "frontmatter: name" fm_has "$SKILL" "name: codex-pipeline"
check "frontmatter: disable-model-invocation: true (явная активация)" fm_has "$SKILL" "disable-model-invocation: true"
check "frontmatter: есть description" sh -c "awk 'NR>1 && \$0==\"---\" {exit} /^description: ./ {f=1} END {exit !f}' '$SKILL'"

for needle in \
  "--write" \
  "--model gpt-6.1-sol" \
  "--effort high" \
  "--cwd" \
  "--resume-last" \
  "worktree.sh create" \
  "worktree.sh path" \
  "references/task-brief.md" \
  "setup --json" \
  "status" \
  "finishing-a-development-branch"; do
  check "SKILL.md содержит '$needle'" has "$SKILL" "$needle"
done

check "references/task-brief.md существует" test -f "$BRIEF"
check "scripts/worktree.sh существует и исполняем" test -x "$SKILL_DIR/scripts/worktree.sh"

for section in "## Разрешения" "## Контекст" "## Цель" "## Файлы в scope" "## Шаги (TDD)" "## Критерии приёмки" "## Команды проверки" "## Формат ответа"; do
  check "шаблон брифа содержит '$section'" has "$BRIEF" "$section"
done
check "шаблон брифа запрещает git-команды" has "$BRIEF" "git-команды"

CLAUDE_MD="$ROOT/CLAUDE.md"
check "CLAUDE.md существует в корне репозитория" test -f "$CLAUDE_MD"
check "CLAUDE.md называет /codex-pipeline" has "$CLAUDE_MD" "/codex-pipeline"
check "CLAUDE.md запрещает самостоятельный вызов codex:codex-rescue" has "$CLAUDE_MD" "codex:codex-rescue"
check "CLAUDE.md требует явной команде пользователя" has "$CLAUDE_MD" "явной команде"

echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
