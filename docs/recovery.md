# Диагностика и восстановление

Все команды выполняются на новой ноде с root/sudo. Native-консоль провайдера остаётся независимым аварийным доступом.

## Прерванная установка

Не удаляйте state и Node key. Повторите тот же проверенный `sudo bash polaris-install.sh`. Фиксируются installation ID, intent/stages и UUID; спорный POST сначала сверяется чтением по собственному маркеру. Чужие совпадения имени/адреса не присваиваются. После SIGTERM/SIGINT повторный запуск должен продолжить установку. При занятом lock дождитесь другого процесса, не удаляйте его принудительно.

Если сообщения API указывают401/403, проверьте expiry/scopes и выдайте новый однодневный API-role токен. Не вставляйте токен в команду, JSON или env. При неподдерживаемой версии Panel остановитесь: не обходите gate. Токен вводится getpass; для автоматизации есть `--token-fd N` с защищённым pipe/FD.

## Сеть

```bash
sudo polaris-node doctor
sudo polaris-node doctor --online
sudo systemctl status polaris-node.service polaris-node-firewall.service
sudo systemctl list-timers polaris-node-renew.timer
sudo polaris-node logs
```

- `Node ONLINE` не появился: проверьте фактический source-IP Panel, доступ Panel→2222 и provider firewall. Исправление: `sudo polaris-node access --panel-ip <точный-IP>`; не открывайте2222 всему Интернету.
- DNS не совпал: создайте/исправьте только новый A/AAAA; уберите лишний AAAA, если IPv6 VPS не настроен. Проверяется полный набор адресов. Не включайте CDN proxy.
- ACME/TLS: проверьте TCP80 снаружи, DNS, время, исходящий443. Не используйте insecure/skip-verification. Таймер продлевает и перезагружает только собственный Nginx. `systemctl start polaris-node-renew.service` повторяет штатную попытку. BYO TLS требует повторного запуска install с прежними путями после замены валидного сертификата.
- Порт занят чужим PID: освободите его по собственному решению либо выберите отдельную чистую VPS. Установщик не убивает процесс и не подбирает другие порты за спиной владельца.
- Docker/APT занят/недоступен: устраните блокировку штатным способом, повторите. Не удаляйте чужие контейнеры/volumes, не делайте prune. Captured error bodies скрываются, выводится категория. Не отправляйте сырые private логи в публичный issue.

## Скрытие и локальный откат

```bash
sudo polaris-node unpublish
sudo polaris-node rollback --remove
```

Первая команда требует отдельный scoped publish-token и `UNPUBLISH <имя>`; она работает без ONLINE Node. Вторая требует `ROLLBACK <имя>`. Скрывается только собственный Host; из Squad удаляется только доказанно добавленное право. Если native API недоступен, владелец сначала вручную выставляет своему Host **disabled и hidden**, затем восстанавливает связь для сверки. Не редактируйте закрытый state вручную.

Откат останавливает только собственные контейнеры/unit/timer, удаляет только свои hooks/chain. Docker, остальные контейнеры, зависимости, SSH и firewall default policies сохраняются. Private state, TLS, Node key и remote hidden records сохранены для повторной установки. Это не uninstall всей VPS.

Snapshot после обновления или allowlist-правки указан в выводе и лежит `/var/lib/polaris-node/backups/*.tar.gz` (root0600). Возврат:

```bash
sudo polaris-node rollback --snapshot <точное-имя.tar.gz>
```

Весь архив проверяется до записи: только известные обычные файлы, без duplicate/path traversal/symlink, совпадающие installation ID/remote UUID, ограниченный размер и неизменная существующая Node identity. State удалённой публикации сохраняется текущим. После восстановления проверяйте doctor/online и внешний data plane. Snapshot от частичной установки без CLI/runtime годится как ручное evidence, но не для автоматического runtime-restore.

## Обновления

Никаких `latest`. Сначала проверьте новую подпись/доверенный SHA и compatibility matrix. Запустите новый verified installer с `update`; собственный snapshot создаётся до изменений. При ошибке выполняется локальный restore. Если обновление не меняет pins и сам script — no-op. Старые пакеты Docker/Ubuntu автоматически не удаляются/не откатываются.

## Ключи и безопасность

При утрате state или root-компрометации не пытайтесь присвоить имеющиеся remote ресурсы. Сначала скройте старый Host, отзовите временные API-токены и удалите только соответствующие собственные записи в Panel после проверки UUID. Для новой VPS используйте новую регистрацию и новые native/TLS keys. Никогда не копируйте старую private identity между нодами.
