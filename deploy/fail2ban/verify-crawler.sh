#!/bin/sh
# fail2ban ignorecommand: exit 0 = never ban this IP, exit 1 = normal handling.
# Deployed to /etc/fail2ban/verify-crawler.sh (chmod 755).
#
# Search engines that publish reverse-DNS verification (Google, Bing, Apple,
# Yandex) are exempt from every jail, checked the way Google documents it:
# reverse-resolve the IP, require a name under the engine's domain, then
# forward-resolve that name and require it to contain the same IP. A probe bot
# that merely *says* "Googlebot" in its user agent fails this (the 2026-09-08
# logs had one at 94.154.46.242 doing 300 requests/s against /.env with that
# UA), so the user agent is deliberately NOT consulted anywhere in fail2ban.
#
# fail2ban caches the answer per IP for a day (ignorecache in jail.local), so
# this costs one DNS round-trip per offending IP per day.
ip="$1"
[ -n "$ip" ] || exit 1
name=$(host "$ip" 2>/dev/null | awk '/pointer/ {print $NF; exit}')
[ -n "$name" ] || exit 1
case "$name" in
  *.googlebot.com.|*.google.com.|*.search.msn.com.|*.applebot.apple.com.|*.yandex.ru.|*.yandex.net.|*.yandex.com.) ;;
  *) exit 1 ;;
esac
host "$name" 2>/dev/null | grep -qF " $ip" && exit 0
exit 1
