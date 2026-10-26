"""Fail-closed checks of effective runtime authority, including inherited privileges."""

from sqlalchemy import text


class DatabasePrivilegeError(RuntimeError):
    pass


def validate_runtime(connection):
    unsafe = connection.scalar(
        text("""
        SELECT EXISTS (
          SELECT 1 FROM pg_roles r
          WHERE pg_has_role(current_user, r.oid, 'MEMBER')
            AND (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolbypassrls)
        ) OR has_database_privilege(current_user, current_database(), 'CREATE')
          OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
                     WHERE r.rolname=current_user)
          OR has_database_privilege(current_user, current_database(), 'TEMP')
          OR EXISTS (SELECT 1 FROM pg_namespace n
                     WHERE n.nspname !~ '^pg_' AND n.nspname != 'information_schema'
                     AND has_schema_privilege(current_user,n.oid,'CREATE'))
          OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                     WHERE n.nspname=current_schema()
                     AND pg_has_role(current_user,c.relowner,'MEMBER'))
    """)
    )
    if unsafe:
        raise DatabasePrivilegeError("DATABASE_RUNTIME_PRIVILEGES_UNSAFE")
    return True
