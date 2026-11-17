# Polaris Node Installer 1.0.0

Автономная подготовка **новой** Ubuntu VPS для Follow Your Polaris: Docker, официальный Remnawave Node, Xray VLESS/XHTTP `packet-up`, Nginx HTTPS/HTTP2, ACME, регистрация Node/Profile/Host. После установки Host **disabled + hidden**, не добавлен в существующий Squad и не попадает в текущие подписки.

**Статус:** инфраструктура и автоматический ACME проверены на настоящих изолированных Ubuntu22/24. Полный VPN roundtrip пока **не подтверждён**: контрольный HTTPS-запрос через XHTTP завершился timeout, причина оставшегося сбоя не установлена. До проверки владельцем используйте только изолированного тестового пользователя и оставляйте основной Host скрытым. Релиз предназначен для изолированного первого теста.

Поддерживаются Ubuntu Server **22.04 / 24.04 amd64**, systemd, ≥1 ГБ RAM (MemTotal ≥900 MiB и доступно ≥400 MiB), ≥4 ГБ свободного диска, 1 CPU. Проверенная матрица: Panel **3.4.11**, Node **3.4.6**, Xray **26.11.9**, Docker **29.9.2**, Compose **2.40.3**. Образы закреплены digest; другой Panel блокируется до записи. ARM и более новые версии Panel пока не заявлены.

## Безопасная установка v1.0.0

[GitHub Release v1.0.0](https://github.com/HydraByHard/polaris-node-installer/releases/tag/v1.0.0) — prerelease для первого изолированного теста. Поддерживаются чистые Ubuntu Server22.04/24.04 AMD64; выполняйте команды в root native-консоли. Полноценная работа VPN не заявлена: CURL28 остаётся неразрешённым.

Подписанные установочные файлы хранятся в версионированном каталоге [`release/v1.0.0`](release/v1.0.0). GitHub Release содержит ссылки на эти файлы. Нативный upload в Release Assets недоступен текущей runtime-авторизации (`uploads.github.com`:401); дополнительные repository-admin права для установки не нужны.

Скачиваются installer, его Ed25519 signature и публичный ключ. Оба SHA256 ниже нужно закрепить из доверенного отчёта владельца; скачанный рядом checksum или ключ без сверки не доказывает подлинность.

```bash
curl --fail --fail-early --location --proto '=https' --proto-redir '=https' --tlsv1.2 --remote-name 'https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/{polaris-install.sh,polaris-install.sh.sig,release-signing-public.pem}' &&
printf '%s  %s\n' 556a5ba3df35892cac49bf946fe8889640bea538522996a32e303544bdc5d69a polaris-install.sh 0ee4e2704e97c16fa647296eed27b7332bf382da498fe08d637b583a24cc2400 release-signing-public.pem | sha256sum -c - &&
openssl pkeyutl -verify -rawin -pubin -inkey release-signing-public.pem -in polaris-install.sh -sigfile polaris-install.sh.sig && bash ./polaris-install.sh
```

При любой ошибке цепочка `&&` остановится до исполнения. Ожидаются два `OK` и `Signature Verified Successfully`. Под пользователем с sudo замените последнюю команду на `sudo bash ./polaris-install.sh`. Не используйте `curl | bash` и не отключайте TLS verification. [Подпись, архивы и воспроизводимая сборка](docs/release.md).

Установщик спросит имя (`finland-01`), страну (`FI`, `DE`, `NL`), новый домен, адрес Panel, IPv4 VPS и **фактический исходящий IPv4 Panel**. Для текущей прямой схемы последний — `208.123.185.211`; если появится NAT/CDN, его нужно проверить. Не указывайте IP CDN. Email ACME необязателен.

1. В Panel под владельцем создайте API-токен со сроком **1 день** и только перечисленными ниже десятью scopes. Вставьте его в скрытый запрос установщика. Административный пароль не нужен.
2. При запросе создайте у своего DNS-провайдера `A <новый-домен> → <IPv4 новой VPS>`, без проксирования CDN. Если явно настроен IPv6 — также AAAA. Дождитесь разрешения DNS и нажмите Enter. Существующие panel/sub/backup не меняются.
3. Разрешите у провайдера входящие TCP80/443 и TCP2222 **только от Panel**. Встроенный firewall установщика дополнительно проверяет источник. SSH и native-консоль сохраняются.

```text
system:metadata
nodes:list
nodes:get
nodes:create
config-profiles:list
config-profiles:get
config-profiles:create
keygen:get
hosts:list
hosts:create
```

Список также доступен **до установки**, без root и токена: `bash polaris-install.sh scopes`. Создание токена — единственное действие сопряжения в Panel. Native Remnawave 3.4.11 не имеет подтверждённого одноразового enrollment API: Swagger OTT для этого не подходит. Минимальный срок native API-токена — 1 день; он **повторно используем до отзыва/истечения**, а не криптографически одноразовый. Установщик принимает только API-role JWT ≤24 ч, хранит его только в памяти процесса и не умеет самостоятельно отзывать через ADMIN-only API. После установки **удалите токен в Panel**, либо дождитесь его native expiry. Scopes нативные: сервер не привязывает этот токен к одному installation UUID; проверку принадлежности ресурсов выполняет клиент. Выдавайте отдельный токен на одну установку и сразу отзывайте. Длительный или административный JWT отклоняется.

## Результат и публикация

```text
INSTALLATION COMPLETE
STATUS: READY FOR TESTING
Node: ONLINE
Host: VERIFIED
Visibility: HIDDEN (disabled AND hidden)
```

Это результат локальной диагностики и подключения Panel. Внешний VPN-трафик и изоляцию API нужно проверить независимо. Установщик честно показывает `UNKNOWN`, если такой проверки не было.

```bash
sudo polaris-node status
sudo polaris-node doctor --online
sudo polaris-node logs
```

Для `--online` достаточно нового однодневного токена с тремя scopes: `system:metadata`, `nodes:get`, `hosts:list`; проверяются фактическая версия, Node ONLINE и видимость Host. Без токена доступны локальные проверки. `logs` выводит ограниченный хвост с редактированием JWT/native Node identity; не пересылайте исходные Docker-логи.

Для тестирования создайте **отдельного тестового пользователя и Squad** в Panel, разрешите только новый inbound и подготовьте тестовый Host, не меняя `Polaris personal`. Экспортируйте Xray JSON этого пользователя в root-owned файл0600 на новой VPS. Затем:

```bash
sudo polaris-node doctor --test-config /root/polaris-test.json
```

Проверка запускает временный Xray-клиент, отправляет HTTPS через SOCKS → VLESS/XHTTP/TLS/h2 и сравнивает egress с IPv4 новой ноды; контейнер удаляется. Временный клиент явно использует подключённый системный CA bundle (`useSystemCA=true`); проверка сертификата остаётся включённой, исходный JSON не переписывается. Успех не заменяет тест Hiddify с независимого устройства. После теста удалите временные сущности и JSON.

Только после успешного теста выполните **отдельно**:

```bash
sudo polaris-node scopes --purpose publish
sudo polaris-node publish
```

Создайте отдельный однодневный токен с этими восемью scopes. Команда потребует точное `PUBLISH finland-01`, проверит ONLINE и локальный doctor, добавит только свой inbound в `Polaris personal`, сохранив прежние UUID разрешений, затем откроет только свой Host. Ссылки существующих подписок не меняются. **Не редактируйте этот Squad параллельно**: API использует replace-array без CAS; установщик проверяет прочитанное состояние, но не может устранить серверную гонку после последнего чтения.

Обратное скрытие, в том числе при недоступной Node:

```bash
sudo polaris-node unpublish
```

Нужны те же восемь scopes и точное `UNPUBLISH finland-01`. Сначала скрывается Host, затем убирается только inbound, добавление которого доказано журналом этой установки. Ранее существовавшие права не удаляются. Отзовите токен в Panel.

## Обслуживание

- Повторный запуск **того же проверенного скрипта** продолжит этапы с прежними UUID и native Node key. Другую ноду устанавливайте на другой VPS. Имя/домен/порты после начала не меняются.
- `sudo polaris-node access --panel-ip <IP>` безопасно корректирует source-IP allowlist, сохраняя собственный snapshot. Для IPv6 есть `--panel-ip6`; CIDR не принимаются.
- `sudo polaris-node update` использует только pins текущего подписанного установщика. Если версия та же — no-op. Для будущего релиза сначала проверьте его доверенный хеш/подпись и запустите `sudo bash polaris-install.sh update`. Это не `latest` и не автообновление других нод. Для текущего update достаточно `system:metadata`; будущие межверсионные обновления требуют новой проверенной матрицы.
- `sudo polaris-node rollback --snapshot <имя.tar.gz>` возвращает собственный runtime snapshot. `rollback --remove` останавливает только свой runtime/hooks, сохраняет Docker, зависимости, закрытые state/backups и скрытые записи Panel. Требует `ROLLBACK <имя>`. Опубликованный Host сначала скрывается. **Удаление remote записей и Docker не автоматизировано**.
- ACME обновляется собственным systemd-таймером. Для BYO-сертификата renewal остаётся обязанностью владельца; проверка цепочки/имени/срока и соответствия ключа обязательна.

Подробно: [восстановление](docs/recovery.md), [первая реальная установка](docs/first-live.md), [ограничения](docs/limits.md), [тестирование](docs/test-report.md), [API-исследование](research/api-contracts.json).

## Изоляция и файлы

Node API2222 принимает только точные Panel source IP и native mTLS/SNI; Xray8082 слушает loopback. Docker host-network означает INPUT, а не Docker DNAT: собственные IPv4/IPv6 цепочки устанавливаются до старта Node и до Docker при boot. TCP80/443 открываются только для своей VPN-службы. Default policies, чужие цепочки, SSH, Tailscale, чужие контейнеры не очищаются. Existing Docker29 с Compose≥2.40 сохраняется; чужой runtime/routing/NAT без Docker вызывает остановку. При новой установке Docker его **штатные** изменения forwarding/NAT всё же возможны — на используемом VPN/router VPS установка блокируется.

`/opt/polaris-node` и `/var/lib/polaris-node` — root0700; native Node identity/TLS private key0600. Это собственные ключи новой ноды, API-токенов там нет. CLI `/usr/local/bin/polaris-node`; unit-файлы `polaris-node*`. Никакой дополнительный менеджер, домашняя программа или постоянный доступ Codex к Panel не требуется.

## Разработка

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 scripts/build-release.py --output dist
```

Лаборатории [Remnawave](tests/lab/README-remna.md) и [Ubuntu VM](tests/lab/README-vm.md) создают только выделенные тестовые ресурсы. Production не используется.
