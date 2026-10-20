#!/bin/bash
# Puts one backup folder (made by src/workers/backup/exportDatabase.py) into the private backup repository and keeps
# only the newest KEEP backups there. The repository's history is cut to one commit on every run, so what was deleted is
# really gone and the repository stays about KEEP times the size of one backup.
#
#   scripts/publish-backup.sh BACKUP_FOLDER REPOSITORY_URL [KEEP]
#
# The backup folders are named <date>_<time>, so sorting the names sorts them by age. For the push to work, git must be
# able to authenticate to REPOSITORY_URL (the backup workflow supplies a deploy key through GIT_SSH_COMMAND).
set -euo pipefail

backup="${1:?Usage: publish-backup.sh BACKUP_FOLDER REPOSITORY_URL [KEEP]}"
remote="${2:?Usage: publish-backup.sh BACKUP_FOLDER REPOSITORY_URL [KEEP]}"
keep="${3:-30}"

if [ ! -f "$backup/manifest.json" ]; then
  echo "Stopping: $backup is not a backup (it has no manifest.json), so nothing was published." >&2
  exit 2
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

git clone --quiet --depth 1 "$remote" "$work/repo"
cd "$work/repo"

name=$(basename "$backup")
rm -rf "$name"
mkdir "$name"
cp "$backup"/* "$name"/

find . -mindepth 1 -maxdepth 1 -type d ! -name .git -exec basename {} \; | sort -r | tail -n +$((keep + 1)) | while read -r old; do
  echo "Removing the old backup $old"
  rm -rf "$old"
done

git checkout --quiet --orphan snapshot
git add -A
kept=$(find . -mindepth 1 -maxdepth 1 -type d ! -name .git | wc -l | tr -d ' ')
git -c user.name="LeekCF backup" -c user.email="backup@users.noreply.github.com" commit --quiet -m "Backup $name ($kept kept)"
git push --quiet --force origin snapshot:main
echo "Published $name; the backup repository now holds $kept backup(s)."
