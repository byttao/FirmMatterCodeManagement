"""Small, repeatable schema upgrades for existing SQLite installations."""

from sqlalchemy import inspect, text


def migrate_signer_accounts(engine):
    with engine.begin() as connection:
        if "user_id" not in {column["name"] for column in inspect(connection).get_columns("signers")}:
            connection.execute(text("ALTER TABLE signers ADD COLUMN user_id INTEGER REFERENCES users(id)"))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_signers_user_firm "
            "ON signers (user_id, signer_type)"
        ))
