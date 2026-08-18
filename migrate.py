"""Migrations alag se chalane ke liye:

    python migrate.py            # pending migrations apply karo
    python migrate.py --status   # sirf batao kya baaki hai
    python migrate.py --reset    # hiring_agent schema gira kar naye sire se banao

Server start hote hi migrations apne aap chal jaati hain, ye script sirf tab
chahiye jab deploy se pehle ya CI me alag se chalana ho.
"""
import sys


from app import config, db


def main() -> int:
    if not config.DATABASE_URL:
        print("DATABASE_URL .env me nahi mila.")
        return 1

    print(f"Database  : {config.DATABASE_URL.split('@')[-1].split('?')[0]}")
    print(f"Schema    : {config.DB_SCHEMA}")

    if "--reset" in sys.argv:
        confirm = "--yes" in sys.argv
        if not confirm:
            print(f"\n!! --reset schema '{config.DB_SCHEMA}' ki saari tables gira dega.")
            print("   Pakka ho to dobara chalao: python migrate.py --reset --yes")
            return 1
        db.connect_sync(migrate=False)
        if not db.enabled():
            print(f"Connect nahi ho paaya: {db.status()['error']}")
            return 1
        db.drop_schema_sync()
        print("Schema gira diya gaya.")
        db.close_sync()

    if "--status" in sys.argv:
        db.connect_sync(migrate=False)
        if not db.enabled():
            print(f"Connect nahi ho paaya: {db.status()['error']}")
            return 1
        pending = db.pending_migrations()
        print("\nPending  :", ", ".join(pending) if pending else "kuch nahi — sab up to date")
        db.close_sync()
        return 0

    applied = db.connect_sync()
    if not db.enabled():
        print(f"\nConnect nahi ho paaya: {db.status()['error']}")
        return 1

    print("\nApplied  :", ", ".join(applied) if applied else "kuch naya nahi — sab up to date")
    db.close_sync()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
