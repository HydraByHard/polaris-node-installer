# Решения и заключительная проверка

Исходный план: docs/plan.md. Работа ограничена отдельным node-installer; production не используется.

## Принятые решения

1. Native OTT не является enrollment. Используется минимальный native API-role токен на1день только в RAM с ручным отзывом владельцем. Цена ограничения: токен повторно применим до expiry/revoke; это явно показано перед эксплуатацией.
2. Создаются отдельные ConfigProfile/inbound/Node/disabled+hiddenHost. Установка не меняет существующие Squad. Цена: публикация отдельной подтверждённой операцией; сам факт ONLINE не означает успешный внешний VPN.
3. Приватный follow-your-polaris остаётся приватным. Публикуется только самостоятельный экспорт node-installer без истории родителя. Цена: отдельный репозиторий/релиз и отдельный signing key; приватные lab-данные не переносимы автоматически.
4. Authenticated production metadata во время разработки недоступна в разрешённых границах. Runtime проверяет точную3.4.11 до remote-записи. Цена: обновившаяся Panel остановит установку, пока не проверена новая матрица; нельзя обещать неподтверждённую совместимость.
5. Нет server-side CAS для Squad. Два чтения и journal сохраняют обнаруженные старые права; требуется отсутствие параллельных edits. Цена: незаметная гонка после последнего чтения не исключена серверным API.
6. Public IPv6 route, произвольные firewall-managers и production Hiddify не заменяются локальными доказательствами. Цена: до публикации новой реальной ноды владелец выполняет внешний API-denial/data-plane тест.

## Fresh whole-component review

Отдельный reviewer проверил весь компонент, требования, ownership и lifecycle;71 текущих на тот момент тестов прошли. No Critical. Пять Important исправлены одним проходом, с наблюдёнными RED→GREEN и расширением общей suite:

- Pending publication/unpublication journal блокирует локальное удаление runtime.
- Проверяются все parent path components; ancestor symlink/unsafe directory не допускают чужую перезапись.
- TLS material создаётся и проверяется в отдельном поколении; `renameat2(RENAME_EXCHANGE)` переключает всю пару, прежнее поколение сохраняется. Reload failure возвращает предыдущую пару; interrupted staging не меняет активную пару. Snapshot-restore использует тот же путь.
- Restore отпускает state lock, запускает/проверяет собственные systemd units и ACME timer до success.
- Existing supported Docker с отсутствующим/старым Compose получает только pinned plugin. Отдельный официальный APT source/key с проверенным primary fingerprint, negative pins остальных пакетов, simulate guard и --no-remove не позволяют заменять engine/runtime.

Дополнительные реальные/собственные findings: boot /tmp race исправлена root temp=/run и After=systemd-tmpfiles-setup; проверяется первенство собственного INPUT hook; hooks переставляются одной exact-rule транзакцией без foreign index deletion; Docker key bundle не может добавить другой primary key.

Minor deferred: компактный стиль Python и некоторые слитные русские слова в диагностике ухудшают аудит/читаемость. Это не меняет проверенные операции; масштабное форматирование оставлено вне релиза, чтобы не смешивать его с исправлениями безопасности.

Reviewer declined-to-judge разрешены так: native token/CAS ограничения приняты и опубликованы выше; production/Hiddify и full publicIPv6 обозначены непроверенными с обязательным first-live checklist; release authenticity/publicURL подтверждаются отдельной упаковкой/скачиванием; boot failure исправляется и подтверждается настоящим reboot, не предположением о netfilter.

Реальный data-plane прогон дополнительно подтвердил внешний контракт Xray26.11.9: системный CA bundle выбирается только useSystemCA=true. Исправлен только временный диагностический клиент; private-CA RED→GREEN, сертификат проверяется строго и исходный JSON сохраняется.

Результаты тестов и актуальная матрица: test-report.md. Закрытые исходные журналы, tokens, VM disks и signing private key остаются вне Git/релиза.

Ruling: сохраняем feature-ветку приватного родителя без merge/push его истории; готовим самостоятельный Git export. Запрошенная публикация разрешена владельцем после сканирования, но createRepository отвергнут самой GitHub-интеграцией. Цена: один внешний шаг владельца — пустой public repo и доступ интеграции.
Ruling: controlled VPN timeout не назван Cloud-ограничением без доказательства. Код инфраструктуры завершён и пакет проверяем; статус только для изолированной первой проверки, без утверждения работоспособности VPN. Цена: до реального подтверждения Host должен оставаться скрытым.

Publication continuation: владелец создал отдельный public repository и явно разрешил публикацию v1.0.0. Сохранены самостоятельная история экспорта, прежний installer556 и ограничение CURL28. Перед push/Release выполняются новые scans и package/signature checks; production не используется.

Publication delivery ruling: текущая identity работает для API/Git, но uploads.github.com отклоняет её с401. Используем разрешённую запись в тот же репозиторий для доставки подписанных versioned files и ссылок из Release. Цена: файлы не являются нативными Release Assets; для таких attachments нужна отдельная рабочая upload-авторизация. Без обхода credential controls, без раскрытия секретов и без production changes.
