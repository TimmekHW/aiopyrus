"""05_data_management.py — Управление данными организации.
                          Organization data management.

Скрипты автоматизации без бота — просто UserClient.
Запускаются вручную или по расписанию (cron / Task Scheduler).

Automation scripts without a bot — just UserClient.
Run manually or on a schedule (cron / Task Scheduler).

Что показано / What is shown:
  - get_register()   — реестр с фильтрами / register with filters
  - search_tasks()   — параллельный поиск по нескольким формам
  - Каталоги         — get, create, update, sync / Catalogs
  - Участники        — find, create, update, block / Members
  - Роли             — list, create, update / Roles
  - Файлы            — upload, download, attach / Files
  - Объявления       — list, create, comment / Announcements
"""

import asyncio

from aiopyrus import UserClient

LOGIN = "user@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"

# Подставьте реальные ID / Replace with real IDs
FORM_REQUESTS = 321  # форма "Заявки" / Requests form
FORM_TASKS = 322  # форма "Задачи" / Tasks form
CATALOG_ID = 999  # справочник / catalog


# =============================================================================
# 1. Реестр задач / Task register
# =============================================================================


async def demo_register(client: UserClient) -> None:
    print("\n== Реестр / Register ==")

    # Простой реестр — задачи на шагах 1 и 2
    # Simple register — tasks at steps 1 and 2
    tasks = await client.get_register(FORM_REQUESTS, steps=[1, 2])
    print(f"Задач на шагах 1-2: {len(tasks)}")

    # Реестр с фильтрами по дате
    # Register with date filters
    recent = await client.get_register(
        FORM_REQUESTS,
        created_after="2026-01-01",
        modified_after="2026-06-01",
        steps=[1],
        item_count=100,
    )
    print(f"Свежих задач: {len(recent)}")

    # Просроченные задачи / Overdue tasks
    overdue = await client.get_register(FORM_REQUESTS, due_filter="overdue")
    print(f"Просроченных: {len(overdue)}")

    # Параллельный поиск по нескольким формам
    # Parallel search across multiple forms
    # search_tasks() запускает get_register() для каждой формы через asyncio.gather
    # search_tasks() runs get_register() for each form via asyncio.gather
    all_tasks = await client.search_tasks(
        {
            FORM_REQUESTS: [1, 2, 3],  # форма -> шаги / form -> steps
            FORM_TASKS: None,  # None = все шаги / None = all steps
        }
    )
    print(f"Итого по двум формам: {len(all_tasks)}")


# =============================================================================
# 2. Каталоги / Catalogs
# =============================================================================


async def demo_catalogs(client: UserClient) -> None:
    print("\n== Каталоги / Catalogs ==")

    # Список всех каталогов (без данных) / List all catalogs (no items)
    catalogs = await client.get_catalogs()
    print(f"Каталогов в системе: {len(catalogs)}")

    if not catalogs:
        return

    # Полный каталог с данными / Full catalog with items
    cat = await client.get_catalog(catalogs[0].catalog_id)
    print(f"Каталог: {cat.name}  записей: {len(cat.items or [])}")

    # Поиск записи / Find item
    # find_item() ищет по первой колонке (ключевому полю)
    # find_item() searches by first column (key field)
    item = cat.find_item("Москва")
    if item:
        print(f"Найдена запись: {item.values}")

    # Создать каталог / Create catalog
    # new_cat = await client.create_catalog(
    #     name="Города",
    #     headers=["Название", "Регион", "Код"],
    #     items=[
    #         ["Москва", "Москва", "77"],
    #         ["Санкт-Петербург", "Санкт-Петербург", "78"],
    #     ],
    # )

    # Обновить строки (upsert — добавить или обновить) / Update rows (upsert)
    # Использует /diff endpoint — только изменения, не полная замена
    # Uses /diff endpoint — only changes, not full replacement
    # result = await client.update_catalog(
    #     CATALOG_ID,
    #     upsert=[
    #         ["Новосибирск", "Новосибирская область", "54"],
    #         ["Екатеринбург", "Свердловская область", "66"],
    #     ],
    #     delete=["Казань"],
    # )

    # Синхронизировать каталог (полная замена!) / Sync catalog (full replacement!)
    # sync_result = await client.sync_catalog(
    #     CATALOG_ID,
    #     headers=["Название", "Регион", "Код"],
    #     items=[["Москва", "Москва", "77"]],
    #     apply=True,   # False = dry run (только проверка / check only)
    # )


# =============================================================================
# 3. Участники / Members
# =============================================================================


async def demo_members(client: UserClient) -> None:
    print("\n== Участники / Members ==")

    # Все участники / All members
    members = await client.get_members()
    print(f"Участников в организации: {len(members)}")

    # Найти по имени / Find by name
    # find_member() ищет по полному имени, имени, фамилии, email, логину
    # find_member() searches full name, first/last name, email, login
    person = await client.find_member("Данил Колбасенко")
    if person:
        print(f"Найден: {person.full_name}  id={person.id}  email={person.email}")
    else:
        print("Не найден / Not found")

    # Найти все совпадения / Find all matches
    # matches = await client.find_members("Колбасенко")
    # for m in matches:
    #     print(f"  {m.full_name} ({m.email})")

    # Создать / Create
    # new = await client.create_member(
    #     first_name="Данил", last_name="Колбасенко",
    #     email="d.kolbasenko@example.com", position="Разработчик",
    # )

    # Обновить / Update
    # await client.update_member(100500, position="Ведущий разработчик")

    # Заблокировать / Block
    # await client.block_member(100500)


# =============================================================================
# 4. Роли / Roles
# =============================================================================


async def demo_roles(client: UserClient) -> None:
    print("\n== Роли / Roles ==")

    roles = await client.get_roles()
    print(f"Ролей: {len(roles)}")
    for role in roles[:5]:
        print(f"  id={role.id}  {role.name}  ({len(role.member_ids)} чел.)")

    # Создать / Create
    # new_role = await client.create_role("Архитекторы", member_ids=[100500])

    # Обновить / Update
    # await client.update_role(42, name="Ведущие архитекторы", member_ids=[100500, 100501])


# =============================================================================
# 5. Файлы / Files
# =============================================================================


async def demo_files(client: UserClient) -> None:
    print("\n== Файлы / Files ==")

    # Загрузить файл (из пути, bytes или BinaryIO) / Upload (from path, bytes or BinaryIO)
    # uploaded = await client.upload_file("/path/to/report.pdf")
    # uploaded = await client.upload_file(b"raw bytes", filename="data.csv")
    # print(f"Загружен: guid={uploaded.guid}")

    # Прикрепить к задаче в комментарии / Attach to task in a comment
    # await client.comment_task(12345678, text="Отчёт прилагаю.", attachments=[uploaded.guid])

    # Скачать файл / Download file
    # content: bytes = await client.download_file("some-guid")
    # with open("downloaded.pdf", "wb") as f:
    #     f.write(content)

    print("  (все операции закомментированы / all ops commented out)")


# =============================================================================
# 6. Объявления / Announcements
# =============================================================================


async def demo_announcements(client: UserClient) -> None:
    print("\n== Объявления / Announcements ==")

    announcements = await client.get_announcements()
    print(f"Объявлений: {len(announcements)}")

    # Создать / Create
    # ann = await client.create_announcement(text="Плановые работы в субботу 02:00-06:00.")

    # Добавить комментарий / Add comment
    # await client.comment_announcement(ann.id, text="Работы завершены раньше срока.")


# =============================================================================
# Запуск / Run
# =============================================================================


async def main() -> None:
    async with UserClient(login=LOGIN, security_key=SECURITY_KEY) as client:
        await demo_register(client)
        await demo_catalogs(client)
        await demo_members(client)
        await demo_roles(client)
        await demo_files(client)
        await demo_announcements(client)


if __name__ == "__main__":
    asyncio.run(main())
