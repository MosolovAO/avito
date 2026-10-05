#!/usr/bin/env bash
# Тесты worktree.sh на одноразовом git-репозитории во временной папке.
# Запуск: bash .claude/skills/codex-pipeline/scripts/test_worktree.sh
# Подробный вывод упавших тестов: VERBOSE=1 bash …/test_worktree.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/worktree.sh"
PASS=0
FAIL=0

# Каждый тест выполняется в подоболочке, поэтому cd, trap и export не протекают между тестами.
setup_repo() {
  TMP="$(mktemp -d)"
  TMP="$(cd "$TMP" && pwd -P)"
  trap 'rm -rf "$TMP"' EXIT
  REPO="$TMP/main"
  export CODEX_WORKTREE_ROOT="$TMP/wt"
  mkdir -p "$REPO/frontend"
  cd "$REPO" || exit 1
  git init -q -b main
  git config user.email test@example.com
  git config user.name test
  git config commit.gpgsign false
  printf 'venv/\nnode_modules\n' > .gitignore
  echo one > app.txt
  git add -A
  git commit -q -m base
  git tag base-tag
  echo two >> app.txt
  git commit -q -am second
  mkdir -p venv/bin frontend/node_modules
  echo dirty > uncommitted.txt
}

t_create() {
  setup_repo
  out="$("$SCRIPT" create foo)"
  rc=$?
  path="$(printf '%s\n' "$out" | tail -n1)"
  [ "$rc" -eq 0 ] \
    && [ "$path" = "$CODEX_WORKTREE_ROOT/foo" ] \
    && [ -f "$path/.git" ] \
    && git rev-parse --verify -q refs/heads/codex/foo >/dev/null \
    && [ "$(git rev-parse codex/foo)" = "$(git rev-parse HEAD)" ]
}

t_symlinks() {
  setup_repo
  "$SCRIPT" create foo >/dev/null || return 1
  w="$CODEX_WORKTREE_ROOT/foo"
  [ -L "$w/venv" ] \
    && [ "$(readlink "$w/venv")" = "$REPO/venv" ] \
    && [ -L "$w/frontend/node_modules" ] \
    && [ "$(readlink "$w/frontend/node_modules")" = "$REPO/frontend/node_modules" ]
}

t_symlinks_absent() {
  setup_repo
  rm -rf venv frontend/node_modules
  "$SCRIPT" create foo >/dev/null || return 1
  w="$CODEX_WORKTREE_ROOT/foo"
  [ ! -e "$w/venv" ] && [ ! -e "$w/frontend/node_modules" ]
}

t_clean_status() {
  setup_repo
  before="$(git status --porcelain)"
  "$SCRIPT" create foo >/dev/null || return 1
  [ -z "$(git -C "$CODEX_WORKTREE_ROOT/foo" status --porcelain)" ] \
    && [ "$(git status --porcelain)" = "$before" ] \
    && [ ! -e "$CODEX_WORKTREE_ROOT/foo/uncommitted.txt" ]
}

t_base_ref() {
  setup_repo
  "$SCRIPT" create old base-tag >/dev/null || return 1
  [ "$(git rev-parse codex/old)" = "$(git rev-parse 'base-tag^{commit}')" ] \
    && [ "$(git rev-parse codex/old)" != "$(git rev-parse HEAD)" ]
}

t_invalid_slug_variants() {
  setup_repo
  for bad in 'Bad Slug' 'a/b' '..' '' '-x' 'UPPER'; do
    "$SCRIPT" create "$bad" >/dev/null 2>&1
    [ $? -eq 2 ] || return 1
  done
  [ ! -e "$CODEX_WORKTREE_ROOT" ] && [ -z "$(git branch --list 'codex/*')" ]
}

t_unknown_base() {
  setup_repo
  "$SCRIPT" create foo no-such-ref >/dev/null 2>&1
  rc=$?
  [ "$rc" -eq 2 ] \
    && ! git rev-parse --verify -q refs/heads/codex/foo >/dev/null \
    && [ ! -e "$CODEX_WORKTREE_ROOT/foo" ]
}

t_empty_repo() {
  TMP="$(mktemp -d)"
  TMP="$(cd "$TMP" && pwd -P)"
  trap 'rm -rf "$TMP"' EXIT
  export CODEX_WORKTREE_ROOT="$TMP/wt"
  mkdir "$TMP/main"
  cd "$TMP/main" || exit 1
  git init -q -b main
  "$SCRIPT" create foo >/dev/null 2>&1
  rc=$?
  [ "$rc" -eq 2 ] && [ ! -e "$CODEX_WORKTREE_ROOT" ]
}

t_existing_branch() {
  setup_repo
  git branch codex/foo
  "$SCRIPT" create foo >/dev/null 2>&1
  [ $? -eq 3 ]
}

t_existing_path() {
  setup_repo
  mkdir -p "$CODEX_WORKTREE_ROOT/foo"
  "$SCRIPT" create foo >/dev/null 2>&1
  rc=$?
  [ "$rc" -eq 3 ] && ! git rev-parse --verify -q refs/heads/codex/foo >/dev/null
}

t_from_linked_worktree() {
  setup_repo
  "$SCRIPT" create foo >/dev/null || return 1
  cd "$CODEX_WORKTREE_ROOT/foo" || return 1
  out="$("$SCRIPT" create bar)"
  rc=$?
  path="$(printf '%s\n' "$out" | tail -n1)"
  [ "$rc" -eq 0 ] \
    && [ "$path" = "$CODEX_WORKTREE_ROOT/bar" ] \
    && [ "$(readlink "$path/venv")" = "$REPO/venv" ]
}

t_path() {
  setup_repo
  "$SCRIPT" path foo >/dev/null 2>&1
  [ $? -eq 1 ] || return 1
  "$SCRIPT" create foo >/dev/null || return 1
  [ "$("$SCRIPT" path foo)" = "$CODEX_WORKTREE_ROOT/foo" ]
}

t_remove() {
  setup_repo
  "$SCRIPT" create foo >/dev/null || return 1
  "$SCRIPT" remove foo >/dev/null || return 1
  [ ! -e "$CODEX_WORKTREE_ROOT/foo" ] \
    && git rev-parse --verify -q refs/heads/codex/foo >/dev/null \
    && "$SCRIPT" remove foo >/dev/null
}

t_remove_dirty() {
  setup_repo
  "$SCRIPT" create foo >/dev/null || return 1
  echo x > "$CODEX_WORKTREE_ROOT/foo/new.txt"
  "$SCRIPT" remove foo >/dev/null 2>&1
  rc=$?
  [ "$rc" -eq 3 ] \
    && [ -e "$CODEX_WORKTREE_ROOT/foo/new.txt" ] \
    && "$SCRIPT" remove foo --force >/dev/null \
    && [ ! -e "$CODEX_WORKTREE_ROOT/foo" ]
}

t_remove_keeps_main_deps() {
  setup_repo
  touch venv/bin/python frontend/node_modules/pkg
  "$SCRIPT" create foo >/dev/null || return 1
  "$SCRIPT" remove foo >/dev/null || return 1
  [ -e "$REPO/venv/bin/python" ] && [ -e "$REPO/frontend/node_modules/pkg" ]
}

t_usage() {
  setup_repo
  "$SCRIPT" >/dev/null 2>&1
  [ $? -eq 2 ] || return 1
  "$SCRIPT" frobnicate foo >/dev/null 2>&1
  [ $? -eq 2 ]
}

run() {
  name="$1"
  if [ -n "${VERBOSE:-}" ]; then
    ( set -x; "$name" )
  else
    ( "$name" ) >/dev/null 2>&1
  fi
  if [ $? -eq 0 ]; then
    PASS=$((PASS + 1))
    echo "ok   - $name"
  else
    FAIL=$((FAIL + 1))
    echo "FAIL - $name"
  fi
}

for t in t_create t_symlinks t_symlinks_absent t_clean_status t_base_ref \
  t_invalid_slug_variants t_unknown_base t_empty_repo t_existing_branch \
  t_existing_path t_from_linked_worktree t_path t_remove t_remove_dirty \
  t_remove_keeps_main_deps t_usage; do
  run "$t"
done

echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
