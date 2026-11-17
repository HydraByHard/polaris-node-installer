# Отчёт изолированных проверок

Дата:17.11.2026, Europe/Moscow. Production не использовался и не изменялся. Матрица инфраструктурных VM-тестов: installer `5f83521ec35b9f83bba0ffddfb47a0ceb01deac1bd87219f277b81177a66d067`. Последующий client-CA-only candidate: `556a5ba3df35892cac49bf946fe8889640bea538522996a32e303544bdc5d69a`.

## Автоматизированные проверки

83 unit/integration/release проверок — PASS. Проверяются ошибки API/токена, ambiguous POST, собственность UUID, hidden+disabled, подтверждение публикации, её восстановление/скрытие, конкурентное изменение Squad, атомарный state, lock, symlink-ancestors, секреты, версия/ресурсы/порты, firewall, release tampering/подпись, staging restore и TLS pair interruption/reload failure. Подробные имена — tests/test_*.py.

Реальная отдельная Panel3.4.11 build230 на official digest:29 contract assertions PASS; native mTLS Node3.4.6/Xray26.11.9 ONLINE; Registrar ensure/idempotency/publish/unpublish/recovery PASS. Предсуществующие синтетические Node/Profile/Host/Squad/user/subscription сохранены. Enrollment token не может читать users/Squad или изменять/удалять существующие ресурсы, включая собственный API-token.

## Ubuntu VM

Настоящие Ubuntu22.04.5 (kernel5.15) и24.04.5 (kernel6.8) AMD64, по2 vCPU/2ГБ RAM, QEMU/TCG, systemd/netfilter, безprivileged/KVM/hostsocket. На обеих выполнены установка отсутствующего Docker, Node/Profile/hiddenHost, строгий TLS/HTTP2, Node ONLINE, Xray schema+процесс, повторный запуск без смены UUID/nativekey/TLSkey и без дубликатов. Сохранены чужие IPv4/IPv6 sentinel rules и default policies. Чужой listener8082 вызывает отказ без убийства процесса или замены контейнеров. С доверенного Panel native API работает; недоверенный TLS/application probe2222/8082 таймаутится с ростом guestDROP counters.

Первый холодный APT update достиг300s timeout; сохранённый partialstate успешно продолжен. В итоговом Runner отключены загрузки переводов только для своего apt-вызова, заданы bounded retries/timeouts. Реальные прогоны обнаружили и исправили формат ss и имя native процесса rw-core. Проверка OS reboot обнаружила гонку раннего /tmp с systemd-tmpfiles; защитная служба отказала, Node осталась выключенной. Исправлены root temp→/run и ordering; финальный5f83 installer повторно установлен с точным readback hash на обеих Ubuntu. Настоящий reboot24 прошёл: новый bootID, firewall→Docker→Node, активные units, ONLINE и LOCAL_CHECKS_PASS, UUID/keys/policies прежние. На22 также подтверждён reboot/lifecycle; синтетические DNS/proxy mappings исправлены только в лабораторном cloud-init, не в installer.

## ACME и data plane

Настоящие pinned Certbot5.10.0 + Pebble2.10.3, строгий CA trust, HTTP01 через Nginx, без bypassvalidation: изолированный bridge probe issuance+forcedrenewal PASS, serial изменился и повторный challenge действительно выполнен. На настоящем22 guest установленный5f83 System.acme выпустил90-дневный сертификат, затем штатная renew-команда при временном100day threshold выпустила новый serial. Atomicpair и Nginx reload представили оба новых serial с verifiedTLS/h2, doctorLOCAL_CHECKS_PASS; threshold восстановлен. Первичная ошибка NotBefore была вызвана5s TCG clockskew; исправлены только часы тестового guest, TLS не отключался и прежний BYO pair оставался активным до успешной проверки. Полный свежий556 ACME CLI с новымPNIstate на прогретых Docker/dependencies прошёл все8этапов, NodeONLINE и hidden+disabledHost, LOCAL_CHECKS_PASS. Установленный timer реально вызвал service→CLI _renew→Certbot HTTP01 renewal→atomicpair→Nginx reload. Представлен новый serial, serviceResultsuccess/exit0, strictTLS/h2 и doctorPASS. Временный100day threshold и timerdrop-in удалены, штатная policy/календарь восстановлены. Controlled data plane описан ниже как отдельный результат.

Прямой Cloud IPify egress недоступен в лабораторной VM. Контролируемый TLS/XHTTP traffic test обозначается отдельно от публичного Internet-egress и production Hiddify. Новый реальный production VPS ещё не установлен.

## Обязательные 20 сценариев

| № | Сценарий | Проверка/статус |
|---|---|---|
|1|Чистая Ubuntu|Реальные22/24, отсутствиеDocker baseline, install/retry PASS|
|2|Существующий Docker|Реально удалён только docker-compose-plugin; installer восстановил2.40.3 из officialAPT, Engine29.9.2/containerd и активныйDocker сохранены PASS|
|3|Недостаток ресурсов|check_resources отрицательные RAM/CPU/disk PASS|
|4|Ошибка GitHub download|Закрытый HTTPS loopback, curl fail/no file PASS; не выдаётся за сбой реальногоGitHub|
|5|Повреждённый installer|Изменённый embeddedpayload не исполняется PASS|
|6|Неверный checksum/signature|Неверный trustedhash и tamperedEd25519 signature отвергнуты PASS|
|7|Panel недоступна|Настоящий отказ TCP к labPanel +CONNECT/URLError tests; state byte-identical PASS|
|8|Ошибка регистрации|Ambiguous commit profile/node/Host восстанавливается бездубликатов PASS|
|9|Неверный/истёкший токен|Localexpired/admin/long-lived reject; real401 подпорченного JWT и403 scopes, state unchanged PASS|
|10|Ошибка Compose|Настоящий malformed Compose отказ, работающие контейнеры сохранены PASS|
|11|Конфликт портов|Настоящий чужой8082 listener сохранён PASS|
|12|DNS ошибка|Настоящий неверный labDNS→INCOMPLETE, без исправления DNS установщиком PASS|
|13|TLS ошибка|Реальный trustedCA cert с неверным hostname отвергнут OpenSSL; activepair/identity unchanged. Atomicpair staging/reload revert tests PASS|
|14|Частичная установка|РеальныйAPTtimeout, intent/key сохранены, retry PASS|
|15|Повторный запуск|РеальныеобеUbuntu, UUID/keys/policies/sentinels unchanged PASS|
|16|Аварийное прерывание|Реальный SIGTERM processgroup при удерживаемом lock; retry сохранил UUID/nativekey PASS; atomicreplace/ambiguouscommit tests PASS|
|17|Безопасный откат|Реальные подтверждённые stop+snapshotrestore: ONLINE/LOCAL_CHECKS_PASS, SSH/Docker/foreignsentinels/keys/UUID/policies сохранены PASS|
|18|Защита admin API|Realnative mTLS allowedsource +untrustedapplicationtimeouts/DROP counters PASS; обеIPv4/IPv6 family в настоящем netnamespace: first-hook/reposition/repeat, foreignACCEPT и policies сохранены PASS|
|19|Нет секретов в логах|Capturedcommand/API errors hidden; redaction/state guards PASS; Gitleaks source clean|
|20|Нет случайной публикации|RealhiddenHost, noexistingSquadassignment; explicitpublish/unpublish journals/scopes PASS|

## Пределы доказательства

- Адреса/PKI/DNS в VM синтетические; publicLet'sEncrypt/DNSprovider и providerfirewall не тестировались.
- IPv6 правила установлены/сохранены в настоящем guestnetfilter; полноценный публичный IPv6 маршрут не предоставлен.
- QEMU hostforward может принять внешний TCP handshake до гостя, поэтому nc-z не считается изоляцией; используются applicationpositivecontrol/timeout и guest counters.
- Доступность exact official APT versions проверена подписанными InRelease/Packages SHA; ARM64metadata не является runtimeтестом.
- Ни действующий productionpanel, ни backupnode не менялись. Доступ Hiddify к новой ноде подтверждает владелец при первом liveтесте.

## Xray trust-store contract

Реальный Xray26.11.9 с доверенным host-CA bundle продолжал использовать встроенные Mozilla roots. Сам bindmount и SSL_CERT_FILE не выбирают системный store: нужен JSON `tlsSettings.useSystemCA=true`. Исходники: [TLS config](https://github.com/XTLS/Xray-core/blob/v26.11.9/transport/internet/tls/config.go), [CA selection](https://github.com/XTLS/Xray-core/blob/v26.11.9/transport/internet/tls/config_other.go), [JSON field](https://github.com/XTLS/Xray-core/blob/v26.11.9/infra/conf/transport_security.go). Private-CA fixture сначала дала UnknownAuthority, затем с флагом прошла TLS/h2 и VLESS tunneling. Регрессия test_traffic.py наблюдалась RED→GREEN. Флаг включается только в краткоживущем диагностическом клиенте; ни allowInsecure, ни global profile/subscription не меняются. Полный controlled-response результат фиксируется отдельно.

## Публикация

Владелец создал отдельный публичный HydraByHard/polaris-node-installer. При продолжении публикации повторно проверяются исходники, package members, воспроизводимость installer, SHA256, Ed25519 signatures и отсутствие секретов. [v1.0.0](https://github.com/HydraByHard/polaris-node-installer/releases/tag/v1.0.0) выпускается как prerelease; runtime installer остаётся byte-identical556a5ba3… . Матрица VM/API относится к предыдущим фактическим прогонам; production и VPS при публикации не используются. CURL28 остаётся INCONCLUSIVE, не объявляется исправленным.

## Итог controlled VPN probe

Полный HTTPS roundtrip **INCONCLUSIVE/не прошёл**: curl28, responseReceived=false на198.18/15 и203.0.113/24. Строгий внешний TLS/h2 и XHTTP GET/POST200, доставка правильного VLESS UUID в nativeXray через read-only gRPC подтверждены. Отдельный временный DIRECT catch-all только для собственного inbound не исправил timeout и удалён; render не менялся по недоказанной гипотезе. Причина оставшегося сбоя не установлена. Успех Internet-egress/Hiddify не заявлен. Синтетические user/Squad/Host, временные client files/rule и дополнительные сети удалены.

Исходящие публичные IPify запросы также были недоступны. Это наблюдение не является доказанной причиной controlled timeout. Реальный внешний Hiddify/VPN-тест на новой VPS остаётся обязательным до публикации Host для пользователей.

Финальный556 artifact установлен на24 с точным CLI readback, прежними UUID/nativekey, ONLINE/LOCAL_CHECKS_PASS/hiddenHost. На22 финальный556 прошёл свежий ACME CLI и реальный установленный timer. Основная20-case матрица сохранена для5f с отдельно задокументированным единственным CA-client изменением.

**Итог:**83 unit/release проверок PASS;54 регрессионных проверки родителя PASS;29 настоящих nativeAPI assertions PASS; обязательная инфраструктурная матрица и ACME timer PASS. Контролируемый VPN payload test остаётся неуспешным/неподтверждённым. Production не менялся.

Publication delivery: push исходников и создание draft Release успешны. Upload endpoint вернул401 Bad credentials. Файлы выпуска помещены в versioned repository directory `release/v1.0.0`; после tag/publication выполняется отдельное unauthenticated скачивание и проверка всех файлов/подписей. Нативные asset attachments не заявляются загруженными. Это не изменяет результат CURL28.
