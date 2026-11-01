#!/bin/sh
candidate=$1
destination=$2
backup=$3
ack=$4
oldpid=$5
pending=$6
result=$7
workdir=$(/usr/bin/dirname "$ack")
cleanup() {
    case "${workdir##*/}" in install-*) /bin/rm -rf "$workdir" ;; esac
}
limit=30
count=0
while /bin/kill -0 "$oldpid" 2>/dev/null; do
    count=$((count+1))
    if [ "$count" -ge "$limit" ]; then
        /bin/echo 'Обновление отменено: Dagami не завершился.' > "$result"
        /bin/rm -rf "$candidate"
        /bin/rm -f "$pending"
        cleanup
        exit 1
    fi
    /bin/sleep 1
done
if ! /bin/mv "$destination" "$backup"; then
    /bin/echo 'Обновление отменено: не удалось сохранить прежнее приложение.' > "$result"
    /usr/bin/open -n "$destination"
    /bin/rm -rf "$candidate"
    /bin/rm -f "$pending"
    cleanup
    exit 1
fi
if /bin/mv "$candidate" "$destination"; then
    /usr/bin/open -n "$destination"
    count=0
    while [ "$count" -lt "$limit" ]; do
        if [ -f "$ack" ]; then
            /bin/echo 'Обновление установлено. Предыдущая копия сохранена рядом с приложением.' > "$result"
            /bin/rm -f "$pending"
            cleanup
            exit 0
        fi
        count=$((count+1))
        /bin/sleep 1
    done
    /bin/ps -axo pid=,comm= | while read -r pid command; do
        if [ "$command" = "$destination/Contents/MacOS/Dagami" ]; then /bin/kill -TERM "$pid" 2>/dev/null; fi
    done
    /bin/sleep 1
    /bin/mv "$destination" "$candidate"
fi
/bin/mv "$backup" "$destination"
/bin/rm -rf "$candidate"
/bin/echo 'Обновление не запустилось: прежняя версия восстановлена.' > "$result"
/bin/rm -f "$pending"
/usr/bin/open -n "$destination"
cleanup
exit 1
