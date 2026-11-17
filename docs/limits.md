# Проверенные границы версии 1.0.0

- Только Ubuntu22.04/24.04 amd64 с systemd; ARM, другие ОС и rootless Docker отклоняются.
- Native API и runtime совместимы с Panel3.4.11/Node3.4.6/Xray26.11.9. Текущая production-версия не читалась с авторизацией во время разработки: публичная metadata возвращает401. Перед любыми remote-записями installer обязан проверить authenticated metadata и остановится при другой версии.
- Ни существующий production ConfigProfile, ни текущие Host/Squad/пользователи не считывались с административными секретами. Создаётся независимый профиль по архитектуре HTTPS/HTTP2/XHTTP packet-up. Реальные Hiddify-клиенты на новой production ноде должен проверить владелец.
- Регистрационный токен native однодневный, scopes хранятся в БД Panel. JWT-проверка локально ограничивает role/expiry; подлинность проверяет сервер при metadata. Токен не одноразовый и остаётся пригодным до ручного отзыва/expiry. Self-revoke недоступен API-role. Серверные scopes действуют на тип ресурсов, а не на конкретный installation ID; ownership проверяет installer. Компрометацию root/provider на новой VPS токен не изолирует.
- DNS API credentials не предоставлены. Установщик находит NS и проверяет A/AAAA; запись создаёт владелец. Никакой автозаписи в зону не заявлено.
- ACME HTTP01 требует публичный TCP80, корректный A/AAAA и разрешённый исходящий HTTPS. Лаборатория использует настоящий Pebble ACME и строгую тестовую цепочку, а не публичный Let's Encrypt. В production указан официальный ACME directory Let's Encrypt.
- TLS/XHTTP используется с локальным Nginx; нет Reality и переноса приватных ключей старого узла. Сниффинг/geo базы не нужны.
- Host создаётся disabled+hidden, profile изолирован от действующих Squad. Публикация отдельно подтверждается. API Squad не имеет CAS; не запускайте параллельное редактирование.
- Статус `LOCAL_CHECKS_PASS` не доказывает доступность снаружи или рабочий VPN. `doctor --online` проверяет Panel; `--test-config` проверяет трафик; независимый источник необходим для отрицательных тестов API. Нет ложного production-ready.
- Backup root-only содержит private Node/TLS keys. Не загружайте его в Git и не пересылайте в чат. Откат локальный, remote записи остаются скрытыми. Состояние публикации и существующая native identity не перематываются старым snapshot.
- Docker штатно добавляет свои networking rules и может изменить FORWARD policy. Установщик не меняет его daemon.json и не flush-ит firewall. На чистой машине без Docker активный NAT/routing/container runtime вызывает остановку.
- Не снимается provider-level firewall, не исправляется сторонний outbound firewall и не меняется SSH. Невозможность связи фиксируется, а не обходится открытием API для всех.
- До первой реальной установки owner должен подтвердить production metadata, actual Panel source-IP, DNS, provider firewall и Hiddify data plane. Разработка не затрагивает действующий VPN.

- Контрольный VPN roundtrip в лаборатории не завершился: curl28 на двух изолированных целевых диапазонах. TLS/h2, XHTTP200 и доставка native-user подтверждены, исходящий HTTPS payload не получен. Причина оставшегося timeout не установлена; это не считается успешным VPN-тестом и не списывается на Cloud без доказательства.
- Репозиторий создан владельцем; исходники и подписанные assets подготовлены для [v1.0.0](https://github.com/HydraByHard/polaris-node-installer/releases/tag/v1.0.0). Релиз имеет статус prerelease. Публикация не означает, что CURL28 устранён или полноценный VPN проверен.
