from pathlib import Path


path = Path("scarletx/main.py")
source = path.read_text(encoding="utf-8")

old_import = "from .migrations import ensure_performance_indexes\n"
new_import = (
    "from .migrations import (\n"
    "    ensure_performance_indexes,\n"
    "    performance_index_migration_required,\n"
    ")\n"
)
if source.count(old_import) != 1:
    raise RuntimeError("expected exactly one migrations import")
source = source.replace(old_import, new_import, 1)

old_startup = (
    "        seed_database_settings(db)\n"
    "        migrate_to_scarletx(db)\n"
    "        with engine.begin() as connection:\n"
    "            ensure_performance_indexes(connection)\n"
)
new_startup = (
    "        seed_database_settings(db)\n"
    "        with engine.connect() as connection:\n"
    "            needs_performance_index_migration = performance_index_migration_required(connection)\n"
    "        if needs_performance_index_migration:\n"
    "            migration_settings = load_database_settings(db)\n"
    "            create_backup(\n"
    "                db,\n"
    "                migration_settings.backup_directory,\n"
    "                migration_settings.backup_keep,\n"
    "            )\n"
    "        migrate_to_scarletx(db)\n"
    "        with engine.begin() as connection:\n"
    "            ensure_performance_indexes(connection)\n"
)
if source.count(old_startup) != 1:
    raise RuntimeError("expected exactly one startup migration block")
source = source.replace(old_startup, new_startup, 1)

path.write_text(source, encoding="utf-8")
