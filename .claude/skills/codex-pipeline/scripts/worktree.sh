#!/usr/bin/env bash
# Создаёт, находит и удаляет изолированный git worktree для запуска codex-pipeline.
#
#   worktree.sh create <slug> [base-ref]   создать ветку codex/<slug> и worktree; путь — последняя строка stdout
#   worktree.sh path <slug>                напечатать путь существующего worktree
#   worktree.sh remove <slug> [--force]    удалить worktree (ветка сохраняется)
#
# Коды выхода: 0 ок; 1 worktree не найден (только path); 2 неверные аргументы или base-ref;
# 3 конфликт (ветка или путь уже есть) либо грязный worktree при remove.
# Корень worktree'ов: $CODEX_WORKTREE_ROOT или <родитель репозитория>/<имя репозитория>.codex-worktrees.
set -u

# Зависимости, которые ссылаются из worktree на основное дерево (только для чтения).
LINKS=("venv" "frontend/node_modules")

die() {
  local code="$1"
  shift
  echo "worktree.sh: $*" >&2
  exit "$code"
}

usage() {
  die 2 "использование: worktree.sh create <slug> [base-ref] | path <slug> | remove <slug> [--force]"
}

[ $# -ge 2 ] || usage
cmd="$1"
slug="$2"
shift 2

slug_re='^[a-z0-9][a-z0-9-]*$'
[[ "$slug" =~ $slug_re ]] || die 2 "недопустимый slug '$slug': разрешены строчные латинские буквы, цифры и дефис"

common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || die 2 "текущая папка не внутри git-репозитория"
main="$(dirname "$common")"
root="${CODEX_WORKTREE_ROOT:-$(dirname "$main")/$(basename "$main").codex-worktrees}"
wt="$root/$slug"
branch="codex/$slug"

create() {
  local base="${1:-HEAD}"
  git rev-parse --verify -q "$base^{commit}" >/dev/null || die 2 "неизвестный base-ref: $base"
  if git show-ref --verify -q "refs/heads/$branch"; then
    die 3 "ветка $branch уже существует"
  fi
  [ ! -e "$wt" ] || die 3 "путь $wt уже существует"

  mkdir -p "$root"
  git worktree add -q -b "$branch" "$wt" "$base" || die 3 "git worktree add не удался"

  # Симлинк на каталог не попадает под шаблон «venv/», поэтому исключаем явно (файл общий для всех worktree).
  local exclude="$common/info/exclude"
  mkdir -p "$(dirname "$exclude")"
  local rel
  for rel in "${LINKS[@]}"; do
    grep -qxF "/$rel" "$exclude" 2>/dev/null || echo "/$rel" >> "$exclude"
    if [ -e "$main/$rel" ] && [ ! -e "$wt/$rel" ]; then
      mkdir -p "$wt/$(dirname "$rel")"
      ln -s "$main/$rel" "$wt/$rel"
    fi
  done

  echo "$wt"
}

path() {
  [ -d "$wt" ] || exit 1
  echo "$wt"
}

remove() {
  local force=0
  [ "${1:-}" = "--force" ] && force=1

  git worktree prune
  if [ ! -e "$wt" ]; then
    echo "worktree $wt не найден, удалять нечего"
    return 0
  fi
  if [ "$force" -eq 0 ] && [ -n "$(git -C "$wt" status --porcelain)" ]; then
    die 3 "в $wt есть незакоммиченные изменения; для удаления используй --force"
  fi

  # Сначала убираем сами симлинки (rm без -r), чтобы удаление никогда не дошло до основного дерева.
  local rel
  for rel in "${LINKS[@]}"; do
    [ -L "$wt/$rel" ] && rm "$wt/$rel"
  done

  if [ "$force" -eq 1 ]; then
    git worktree remove --force "$wt" || die 3 "git worktree remove не удался"
  else
    git worktree remove "$wt" || die 3 "git worktree remove не удался"
  fi
  echo "worktree $wt удалён; ветка $branch сохранена"
}

case "$cmd" in
  create) create "$@" ;;
  path) path ;;
  remove) remove "$@" ;;
  *) usage ;;
esac
